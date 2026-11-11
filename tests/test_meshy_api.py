"""Meshy client retry/poll semantics, payloads, catalog, and the mesh review gate."""

from __future__ import annotations

import asyncio
import json
import time
import uuid

import httpx
import pytest
from asset_assembly_automator.clients import meshy_client as mc
from asset_assembly_automator.clients.animation_catalog import (
    AnimationCatalog,
    normalize_catalog_response,
)
from asset_assembly_automator.clients.meshy_client import (
    MeshyApiError,
    MeshyClient,
    MeshyCreateUncertainError,
    MeshyPollTimeout,
    consumed_credits,
    describe_task_failure,
    is_transient_task_failure,
)
from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.state_machine import MANUAL_GATES, StageId, next_stage
from asset_assembly_automator.orchestrator.runner import PipelineRunner
from PIL import Image

I2D = "/openapi/v1/image-to-3d"


def _client(handler, sleeps: list[float]) -> MeshyClient:
    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return MeshyClient(api_key="test-key", transport=httpx.MockTransport(handler), sleep=fake_sleep)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _tid() -> str:
    return f"task-{uuid.uuid4()}"


# --- create -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_does_not_retry_client_errors():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(400, json={"message": "image_url is invalid"})

    client = _client(handler, [])
    with pytest.raises(MeshyApiError) as err:
        await client._create(I2D, {"image_url": "x"})
    assert err.value.status_code == 400
    assert calls == ["POST"]


@pytest.mark.asyncio
async def test_create_429_waits_retry_after_then_succeeds():
    task_id = _tid()
    responses = [
        httpx.Response(429, headers={"Retry-After": "7"}, json={"message": "slow down"}),
        httpx.Response(202, json={"result": task_id}),
    ]
    sleeps: list[float] = []
    client = _client(lambda _r: responses.pop(0), sleeps)
    created = await client._create(I2D, {})
    assert created["task_id"] == task_id
    assert sleeps == [7.0]


@pytest.mark.asyncio
async def test_create_5xx_adopts_the_task_meshy_created():
    adopted = _tid()
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(1)
            return httpx.Response(502, text="bad gateway")
        assert request.url.params["sort_by"] == "-created_at"
        return httpx.Response(
            200,
            json=[
                {"id": adopted, "created_at": _now_ms(), "status": "PENDING"},
                {"id": _tid(), "created_at": _now_ms() - 3_600_000, "status": "SUCCEEDED"},
            ],
        )

    sleeps: list[float] = []
    client = _client(handler, sleeps)
    created = await client._create(I2D, {})
    assert created == {"task_id": adopted, "status": "PENDING", "recovered": True}
    assert len(posts) == 1
    assert sleeps == [client.create_recovery_wait]


@pytest.mark.asyncio
async def test_create_5xx_creates_again_only_when_no_task_exists():
    created_id = _tid()
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(1)
            if len(posts) == 1:
                return httpx.Response(500, text="oops")
            return httpx.Response(202, json={"result": created_id})
        return httpx.Response(200, json=[])

    client = _client(handler, [])
    created = await client._create(I2D, {})
    assert created["task_id"] == created_id
    assert len(posts) == 2


@pytest.mark.asyncio
async def test_create_gives_up_after_second_unknown_outcome():
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(1)
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json=[])

    client = _client(handler, [])
    with pytest.raises(MeshyCreateUncertainError):
        await client._create(I2D, {})
    assert len(posts) == 2


@pytest.mark.asyncio
async def test_create_recovery_ignores_tasks_claimed_by_other_pipelines():
    other = _tid()
    mc._CLAIMED_TASK_IDS.add(other)
    mine = _tid()
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            posts.append(1)
            if len(posts) == 1:
                return httpx.Response(502, text="bad gateway")
            return httpx.Response(202, json={"result": mine})
        return httpx.Response(200, json=[{"id": other, "created_at": _now_ms()}])

    client = _client(handler, [])
    created = await client._create(I2D, {})
    assert created["task_id"] == mine
    assert len(posts) == 2


@pytest.mark.asyncio
async def test_create_recovery_refuses_to_guess_between_candidates():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(502, text="bad gateway")
        return httpx.Response(
            200,
            json=[{"id": _tid(), "created_at": _now_ms()}, {"id": _tid(), "created_at": _now_ms()}],
        )

    client = _client(handler, [])
    with pytest.raises(MeshyCreateUncertainError, match="2 recent tasks"):
        await client._create(I2D, {})


# --- poll -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_uses_retry_after_and_survives_status_errors():
    task_id = _tid()
    responses = [
        httpx.Response(503, text="busy"),
        httpx.Response(
            200,
            headers={"Retry-After": "3"},
            json={"id": task_id, "status": "IN_PROGRESS", "created_at": _now_ms()},
        ),
        httpx.Response(
            200,
            json={"id": task_id, "status": "SUCCEEDED", "consumed_credits": 30},
        ),
    ]
    sleeps: list[float] = []
    client = _client(lambda _r: responses.pop(0), sleeps)
    result = await client.poll_until_done(task_id, "image-to-3d")
    assert result["status"] == "SUCCEEDED"
    assert 3.0 in sleeps
    assert consumed_credits(result) == 30.0


@pytest.mark.asyncio
async def test_poll_keeps_going_when_status_checks_exhaust_retries():
    task_id = _tid()
    responses = [
        httpx.Response(500, text="err"),
        httpx.Response(200, json={"id": task_id, "status": "SUCCEEDED"}),
    ]
    client = _client(lambda _r: responses.pop(0), [])
    client.max_attempts = 1
    result = await client.poll_until_done(task_id, "remesh")
    assert result["status"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_poll_deadline_counts_from_created_at():
    task_id = _tid()
    two_hours_ago = _now_ms() - 2 * 3_600_000

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"id": task_id, "status": "IN_PROGRESS", "created_at": two_hours_ago}
        )

    client = _client(handler, [])
    with pytest.raises(MeshyPollTimeout):
        await client.poll_until_done(task_id, "rigging")


@pytest.mark.asyncio
async def test_multi_image_task_lookup_falls_back_on_404():
    task_id = _tid()
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if "/multi-image-to-3d/" in request.url.path:
            return httpx.Response(200, json={"id": task_id, "status": "SUCCEEDED"})
        return httpx.Response(404, json={"message": "not found"})

    client = _client(handler, [])
    result = await client.get_task_status(task_id, "image-to-3d")
    assert result["status"] == "SUCCEEDED"
    assert paths[-1].endswith(f"/multi-image-to-3d/{task_id}")


def test_task_error_helpers():
    failed = {
        "status": "FAILED",
        "task_error": {"type": "server_error", "code": "E500", "message": "GPU lost"},
    }
    assert is_transient_task_failure(failed)
    assert describe_task_failure(failed) == "FAILED (E500): GPU lost"
    bad_input = {"status": "FAILED", "task_error": {"type": "invalid_input", "message": "x"}}
    assert not is_transient_task_failure(bad_input)
    assert describe_task_failure({"status": "CANCELED"}) == "CANCELED"


# --- payloads ---------------------------------------------------------------


def test_i2d_geometry_resolution():
    build = MeshyClient._build_i2d_payload
    single = {"image_url": "data:image/png;base64,a"}
    assert "geometry_resolution" not in build({"ai_model": "meshy-7.1"}, **single)
    assert (
        build({"ai_model": "meshy-7.1", "geometry_resolution": "4k"}, **single)[
            "geometry_resolution"
        ]
        == "4k"
    )
    assert (
        build({"ai_model": "meshy-7", "geometry_resolution": "4k"}, **single)["geometry_resolution"]
        == "2k"
    )
    assert (
        build({"ai_model": "meshy-7.1", "ultra_mode": True}, **single)["geometry_resolution"]
        == "2k"
    )
    multi = build(
        {"ai_model": "meshy-7.1", "geometry_resolution": "4k"},
        image_urls=["data:a", "data:b"],
    )
    assert multi["geometry_resolution"] == "2k"


def test_smart_topology_model_and_polycount_clamp():
    build = MeshyClient._build_i2d_payload
    cfg = {"model_type": "smart-topology", "target_polycount": 50000}
    single = build(cfg, image_url="data:a")
    assert single["ai_model"] == "meshy-t2.5"
    assert single["target_polycount"] == 30000
    multi = build(cfg, image_urls=["data:a", "data:b"])
    assert multi["ai_model"] == "meshy-t2"
    assert multi["target_polycount"] == 15000


def test_retexture_payload():
    build = MeshyClient._build_retexture_payload
    with pytest.raises(ValueError):
        build({}, input_task_id="t")
    with pytest.raises(ValueError):
        build({}, input_task_id="t", text_style_prompt="x" * 801)
    payload = build(
        {"texture_resolution": "4k"}, input_task_id="t", text_style_prompt=" bronze armor "
    )
    assert payload["text_style_prompt"] == "bronze armor"
    assert payload["ai_model"] == "meshy-7"
    assert payload["enable_original_uv"] is True
    assert payload["texture_resolution"] == "4k"
    by_image = build({}, input_task_id="t", text_style_prompt="ignored", image_style_url="data:x")
    assert by_image["image_style_url"] == "data:x"
    assert "text_style_prompt" not in by_image


def test_v2_i2d_payload_drops_removed_fields():
    build = MeshyClient._build_i2d_payload
    payload = build(
        {
            "ai_model": "meshy-7.1",
            "model_type": "standard",
            "should_texture": True,
            "hd_texture": True,
            "ultra_mode": True,
            "i2d_target_formats": ["fbx", "glb"],
        },
        image_url="data:a",
        api_version="v2",
    )
    assert payload["texture_model"] == "meshy-7"
    assert payload["target_formats"] == ["fbx", "glb"]
    assert payload["texture_resolution"] == "4k"
    assert payload["geometry_resolution"] == "2k"
    assert "model_type" not in payload
    assert "hd_texture" not in payload
    assert "ultra_mode" not in payload
    assert "remove_lighting" not in payload
    smart = build(
        {"model_type": "smart-topology", "should_texture": True},
        image_url="data:a",
        api_version="v2",
    )
    assert smart["ai_model"] == "meshy-t2.5"
    assert "model_type" not in smart
    untextured = build(
        {"should_texture": False, "hd_texture": True},
        image_url="data:a",
        api_version="v2",
    )
    assert "texture_model" not in untextured


def test_v2_retexture_payload():
    build = MeshyClient._build_retexture_payload
    prompt = build({}, input_task_id="t", text_style_prompt=" bronze ", api_version="v2")
    assert prompt["texture_prompt"] == "bronze"
    assert prompt["texture_model"] == "meshy-7"
    assert prompt["uv_mode"] == "preserve"
    assert "text_style_prompt" not in prompt
    assert "ai_model" not in prompt
    image = build(
        {"retexture_enable_original_uv": False},
        input_task_id="t",
        image_style_url="data:x",
        api_version="v2",
    )
    assert image["texture_image_url"] == "data:x"
    assert image["uv_mode"] == "regenerate"
    assert "texture_prompt" not in image


def _v2_client(handler, sleeps: list[float] | None = None) -> MeshyClient:
    async def fake_sleep(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return MeshyClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
        api_version="v2",
    )


@pytest.mark.asyncio
async def test_v2_create_returns_id_and_does_not_retry_parameter_unknown():
    task_id = _tid()
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(400, json={"code": "parameter_unknown", "message": "hd_texture"})
        return httpx.Response(200, json={"id": task_id, "status": "PENDING"})

    client = _v2_client(handler)
    with pytest.raises(MeshyApiError, match="parameter_unknown"):
        await client._create("/openapi/v2/image-to-3d", {"hd_texture": True})
    assert calls == ["POST"]

    created = await client._create("/openapi/v2/image-to-3d", {})
    assert created["task_id"] == task_id
    assert task_id in mc._CLAIMED_TASK_IDS


@pytest.mark.asyncio
async def test_v2_list_recovery_reads_data():
    adopted = _tid()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(502, text="bad gateway")
        assert request.url.path == "/openapi/v2/tasks"
        assert request.url.params["type"] == "image-to-3d"
        return httpx.Response(
            200,
            json={
                "data": [{"id": adopted, "created_at": _now_ms(), "status": "PENDING"}],
                "has_more": True,
            },
        )

    client = _v2_client(handler, [])
    created = await client._create("/openapi/v2/image-to-3d", {})
    assert created["task_id"] == adopted
    assert created["recovered"] is True


@pytest.mark.asyncio
async def test_v2_poll_reads_output_and_stream_failure_falls_back():
    task_id = _tid()
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/stream"):
            return httpx.Response(500, text="stream down")
        return httpx.Response(
            200,
            json={
                "id": task_id,
                "status": "SUCCEEDED",
                "output": {
                    "model_urls": {"fbx": "https://cdn.example/model.fbx", "glb": None},
                    "thumbnail_url": "https://cdn.example/thumb.png",
                },
            },
        )

    client = _v2_client(handler, [])
    result = await client.poll_until_done(task_id, "image-to-3d")
    assert any(path.endswith("/stream") for path in paths)
    assert f"/openapi/v2/tasks/{task_id}" in paths
    assert result["model_urls"]["fbx"] == "https://cdn.example/model.fbx"
    assert result["model_urls"]["glb"] is None
    assert result["thumbnail_url"] == "https://cdn.example/thumb.png"


@pytest.mark.asyncio
async def test_v2_cancel_pending_task_deletes_once():
    task_id = _tid()
    deletes = []
    cancel = asyncio.Event()

    async def fake_sleep(_seconds: float) -> None:
        cancel.set()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/stream"):
            return httpx.Response(404)
        if request.method == "DELETE":
            deletes.append(request.url.path)
            return httpx.Response(200, json={"id": task_id, "status": "CANCELED"})
        return httpx.Response(
            200, json={"id": task_id, "status": "PENDING", "created_at": _now_ms()}
        )

    client = MeshyClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        sleep=fake_sleep,
        api_version="v2",
    )
    with pytest.raises(mc.MeshyTaskCanceled) as err:
        await client.poll_until_done(task_id, "image-to-3d", cancel_event=cancel)
    assert err.value.deleted is True
    assert deletes == [f"/openapi/v2/tasks/{task_id}"]


@pytest.mark.asyncio
async def test_v2_null_texture_urls_are_not_downloaded(tmp_path):
    task_id = _tid()
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        if "/tasks/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "id": task_id,
                    "status": "SUCCEEDED",
                    "output": {
                        "model_urls": {"fbx": "https://cdn.example/model.fbx"},
                        "texture_urls": [
                            {"base_color": "https://cdn.example/base.png", "normal": None}
                        ],
                    },
                },
            )
        return httpx.Response(200, content=b"bytes")

    client = _v2_client(handler, [])
    saved = await client.download_model(task_id, "image-to-3d", save_to=str(tmp_path / "model.fbx"))
    assert len(saved["local_paths"]) == 2
    assert not any("normal" in url for url in fetched)


# --- animation catalog ------------------------------------------------------


def test_catalog_parses_official_and_public_shapes(tmp_path):
    official = [
        {"action_id": 243, "name": "Idle 3", "key": "Idle_3", "category": "Idle"},
        {"action_id": 260, "name": "Idle 30", "key": "Idle_30", "category": "Idle"},
    ]
    public = {
        "code": "OK",
        "result": {
            "total": 1,
            "list": [{"id": 0, "name": "Idle", "key": "Idle", "subCategory": "Basic"}],
        },
    }
    assert normalize_catalog_response(official)[0]["action_id"] == 243
    parsed_public = normalize_catalog_response(public)
    assert parsed_public[0] == {
        "action_id": 0,
        "action_name": "Idle",
        "key": "Idle",
        "category": "",
        "sub_category": "Basic",
        "preview_url": "",
    }

    catalog = AnimationCatalog(cache_path=tmp_path / "catalog.json", api_key="")
    catalog._items = normalize_catalog_response(official) + parsed_public
    assert catalog.find("idle3")["action_id"] == 243
    picked = catalog.resolve(["idle3", "idle", "missing"])
    assert [p["action_id"] for p in picked] == [243, 0]


@pytest.mark.asyncio
async def test_catalog_does_not_cache_empty_results(tmp_path, monkeypatch):
    catalog = AnimationCatalog(cache_path=tmp_path / "catalog.json", api_key="")

    async def empty_fetch():
        return []

    monkeypatch.setattr(catalog, "_fetch", empty_fetch)
    assert await catalog.sync() == []
    assert not (tmp_path / "catalog.json").exists()


# --- mesh review gate -------------------------------------------------------


def test_mesh_review_gate_in_state_machine():
    assert StageId.MESH_REVIEW in MANUAL_GATES
    assert next_stage(StageId.MESHY_I2D) == StageId.MESHY_REMESH
    assert next_stage(StageId.MESHY_I2D, mesh_review=True) == StageId.MESH_REVIEW
    assert next_stage(StageId.MESH_REVIEW, mesh_review=True) == StageId.MESHY_REMESH
    assert next_stage(StageId.MESHY_I2D, asset_kind="vehicle", mesh_review=True) == (
        StageId.MESH_REVIEW
    )


@pytest.fixture
def gated_pipeline(tmp_path):
    db = Database(tmp_path / "test.db")
    project = db.create_project("P", str(tmp_path / "out"))
    pipeline_id = db.create_pipeline(
        project, "Knight", metadata={"mesh_review_enabled": True, "remesh_enabled": True}
    )
    tpose = tmp_path / "knight_tpose.png"
    Image.new("RGB", (64, 64), color=(120, 90, 60)).save(tpose)
    db.add_asset(pipeline_id, "tpose", str(tpose), provider="test")
    db.update_pipeline_stage(pipeline_id, StageId.MESHY_I2D.value)
    return db, pipeline_id


@pytest.mark.asyncio
async def test_dry_run_retexture_then_approve_flows_downstream(gated_pipeline):
    db, pipeline_id = gated_pipeline
    runner = PipelineRunner(db, dry_run=True)

    result = await runner.run_pipeline(pipeline_id)
    assert db.get_pipeline(pipeline_id).current_stage == StageId.MESH_REVIEW.value
    assert "manual gate" in result.message

    retex = await runner.run_stage(
        pipeline_id, StageId.MESHY_RETEXTURE, prompt="weathered bronze plate armor"
    )
    assert retex.success, retex.error
    variant_id = retex.data["task_id"]
    assert db.get_pipeline(pipeline_id).current_stage == StageId.MESH_REVIEW.value
    variant = db.list_external_jobs(pipeline_id, ["retexture"])[-1]
    assert variant["metadata"]["prompt"] == "weathered bronze plate armor"
    assert variant["credits_used"] == 10
    assert variant["metadata"]["thumbnail_path"]

    approved = await runner.run_stage(pipeline_id, StageId.MESH_REVIEW, task_id=variant_id)
    assert approved.success, approved.error
    pipe = db.get_pipeline(pipeline_id)
    assert pipe.metadata["mesh_source"] == {"task_id": variant_id, "task_type": "retexture"}
    assert pipe.current_stage == StageId.MESHY_REMESH.value

    final = await runner.run_pipeline(pipeline_id, until=StageId.MESHY_QC)
    assert final.success, final.error
    remesh = db.list_external_jobs(pipeline_id, ["remesh"])[-1]
    assert remesh["metadata"]["input_task_id"] == variant_id
    rig = db.list_external_jobs(pipeline_id, ["rigging"])[-1]
    assert rig["metadata"]["input_task_id"] == remesh["task_id"]
    anims = db.list_external_jobs(pipeline_id, ["animation"])
    assert sorted(a["metadata"]["action_id"] for a in anims) == [243, 244, 252]
    assert all(a["credits_used"] == 3 for a in anims)

    again = await runner.run_stage(pipeline_id, StageId.MESHY_ANIMATE)
    assert again.success, again.error
    assert len(db.list_external_jobs(pipeline_id, ["animation"])) == 3


@pytest.mark.asyncio
async def test_approving_unknown_variant_fails(gated_pipeline):
    db, pipeline_id = gated_pipeline
    runner = PipelineRunner(db, dry_run=True)
    await runner.run_pipeline(pipeline_id)
    result = await runner.run_stage(pipeline_id, StageId.MESH_REVIEW, task_id="nope")
    assert not result.success
    assert db.get_pipeline(pipeline_id).current_stage == StageId.MESH_REVIEW.value


@pytest.mark.asyncio
async def test_run_meshy_task_recreates_after_transient_failure(gated_pipeline, monkeypatch):
    from asset_assembly_automator.stages import _base
    from asset_assembly_automator.stages._base import StageContext, run_meshy_task

    monkeypatch.setattr(_base, "TRANSIENT_RETRY_DELAY_SECONDS", 0.0)
    db, pipeline_id = gated_pipeline
    outcomes = [
        {"status": "FAILED", "task_error": {"type": "server_error", "message": "GPU lost"}},
        {"status": "SUCCEEDED", "consumed_credits": 5},
    ]
    created: list[str] = []

    class Client:
        async def poll_until_done(self, task_id, task_type, **_kw):
            return outcomes.pop(0)

    async def create():
        created.append(_tid())
        return {"task_id": created[-1]}

    class Writer:
        def log(self, *_a, **_kw):
            pass

    result = await run_meshy_task(
        Client(),
        db,
        StageContext(pipeline_id=pipeline_id),
        Writer(),
        task_type="rigging",
        create=create,
    )
    assert result["status"] == "SUCCEEDED"
    assert len(created) == 2
    jobs = db.list_external_jobs(pipeline_id, ["rigging"])
    assert [j["status"] for j in jobs] == ["FAILED", "SUCCEEDED"]
    assert json.loads(jobs[0]["metadata_json"])["task_error"]["type"] == "server_error"
