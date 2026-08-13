import pytest
from asset_assembly_automator.clients.image_prep import validate_tpose_checklist
from asset_assembly_automator.clients.meshy_client import FakeMeshyClient
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.state_machine import (
    StageId,
    next_stage,
    runnable_stage,
    stage_progress,
)
from asset_assembly_automator.orchestrator.resume import find_resumable_pipelines, should_regenerate
from asset_assembly_automator.orchestrator.runner import PipelineRunner


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    pid = database.create_project("TestProject", str(tmp_path / "out"))
    plid = database.create_pipeline(pid, "TestChar")
    return database, plid


def test_state_machine_next_stage():
    assert next_stage(StageId.PROMPT_BUILD) == StageId.CONCEPT_GENERATE
    assert next_stage(StageId.IMAGE_PREP, multi_view=False) == StageId.MESHY_I2D
    assert next_stage(StageId.IMAGE_PREP, multi_view=True) == StageId.TURNAROUND


def test_stage_progress():
    assert stage_progress(StageId.DRAFT) == 0
    assert stage_progress(StageId.COMPLETE) == 100


@pytest.mark.asyncio
async def test_fake_meshy_pipeline_stages(db):
    database, pipeline_id = db
    client = FakeMeshyClient()
    created = await client.image_to_3d("fake.png")
    task_id = created["task_id"]
    result = await client.poll_until_done(task_id, "image-to-3d")
    assert result["status"] == "SUCCEEDED"
    assert result.get("face_count") == 320000


@pytest.mark.asyncio
async def test_dry_run_pipeline_end_to_end(db, tmp_path):
    database, pipeline_id = db
    runner = PipelineRunner(database, dry_run=True, verbose=False)
    database.update_pipeline_stage(pipeline_id, StageId.PROMPT_BUILD.value)
    result = await runner.run_pipeline(pipeline_id, auto=True)
    pipe = database.get_pipeline(pipeline_id)
    assert result.success or pipe.current_stage in (
        StageId.CONCEPT_REVIEW.value,
        StageId.COMPLETE.value,
        StageId.MESHY_QC.value,
    )


def test_tpose_checklist_missing_file():
    result = validate_tpose_checklist("nonexistent.png")
    assert result["passed"] is False


def test_settings_roundtrip(db):
    database, _ = db
    database.set_setting("show_getting_started", "false")
    assert database.get_setting("show_getting_started") == "false"


def test_pipeline_log_history(db):
    database, pipeline_id = db
    log_id = database.add_log(
        pipeline_id,
        "info",
        "Stage completed",
        context={"stage": "prompt_build"},
    )
    logs = database.get_logs_since(pipeline_id, 0)
    assert len(logs) == 1
    assert logs[0]["id"] == log_id
    assert logs[0]["context"]["stage"] == "prompt_build"
    summary = database.get_log_summary(pipeline_id)
    assert summary["entry_count"] == 1
    assert summary["last_message"] == "Stage completed"


def test_runnable_stage_from_draft():
    assert runnable_stage(StageId.DRAFT) == StageId.PROMPT_BUILD
    assert runnable_stage(StageId.PROMPT_BUILD) == StageId.PROMPT_BUILD


def test_remesh_poly_budget_targets():
    settings = get_settings()
    assert settings.meshy.remesh_target_tris.hero == 300000
    assert settings.meshy.remesh_target_tris.npc == 300000
    assert settings.meshy.remesh_target_tris.crowd == 300000
    assert settings.meshy.i2d_target_polycount.hero == 300000
    assert settings.meshy.i2d_target_polycount.npc == 300000
    assert settings.meshy.hd_texture is True
    assert settings.meshy.smart_topology == "auto"
    assert settings.meshy.i2d_target_formats == ["fbx", "glb"]
    assert settings.meshy.model_type == "standard"
    assert settings.meshy.hard_rig_face_limit == 300000


def test_meshy_settings_for_pipeline_hero(db):
    from asset_assembly_automator.stages._base import meshy_settings_for_pipeline

    database, pipeline_id = db
    pipe = database.get_pipeline(pipeline_id)
    assert pipe is not None
    database.update_pipeline_poly_budget(pipeline_id, "hero")
    pipe = database.get_pipeline(pipeline_id)
    cfg = meshy_settings_for_pipeline(pipe)
    assert cfg["target_polycount"] == 300000
    assert cfg["enable_pbr"] is True
    assert cfg["should_texture"] is True
    assert cfg["texture_resolution"] == "8k"
    assert cfg["model_type"] == "standard"
    assert cfg["target_formats"] == ["fbx", "glb"]


def test_meshy_settings_for_pipeline_game_ready(db):
    from asset_assembly_automator.stages._base import (
        meshy_settings_for_pipeline,
        resolve_i2d_model_type,
    )

    database, pipeline_id = db
    pipe = database.get_pipeline(pipeline_id)
    database.update_pipeline_stage(
        pipeline_id,
        pipe.current_stage,
        metadata={**pipe.metadata, "meshy_preset": "game_ready"},
    )
    pipe = database.get_pipeline(pipeline_id)
    assert resolve_i2d_model_type(pipe) == "smart-topology"
    cfg = meshy_settings_for_pipeline(pipe)
    assert cfg["model_type"] == "smart-topology"
    assert cfg["target_formats"] == ["fbx", "glb"]


def test_meshy_face_count():
    from asset_assembly_automator.stages._base import meshy_face_count

    assert meshy_face_count({"face_count": 120000}) == 120000
    assert meshy_face_count({"result": {"face_count": 45000}}) == 45000
    assert meshy_face_count({"status": "SUCCEEDED"}) is None


def test_remesh_target_for_pipeline_hero(db):
    from asset_assembly_automator.stages._base import remesh_target_for_pipeline

    database, pipeline_id = db
    database.update_pipeline_poly_budget(pipeline_id, "hero")
    pipe = database.get_pipeline(pipeline_id)
    assert pipe is not None
    assert remesh_target_for_pipeline(pipe) == 300000


@pytest.mark.asyncio
async def test_download_meshy_package(tmp_path):
    from asset_assembly_automator.clients.meshy_client import FakeMeshyClient

    client = FakeMeshyClient()
    created = await client.rig("input-task")
    task_id = created["task_id"]
    source = tmp_path / "Source"
    textures = tmp_path / "Textures"
    zip_path = tmp_path / "CHR_Hero_MeshyExport.zip"
    package = await client.download_meshy_package(
        task_id,
        source_dir=source,
        textures_dir=textures,
        zip_path=zip_path,
    )
    assert zip_path.exists()
    assert (source / "Character_output.fbx").exists()
    assert (source / "Animation_Walking_withSkin.fbx").exists()
    assert (source / "Animation_Running_withSkin.fbx").exists()
    assert (textures / "base_color.png").exists()
    assert package["primary_fbx"] == str(source / "Character_output.fbx")
    assert package["texture_source"] == "i2d"


def test_extract_textures_from_fbx(tmp_path):
    from asset_assembly_automator.clients.meshy_client import _extract_textures_from_fbx

    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc"
        b"\xf8\x0f\x00\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    fbx_bytes = b"Kaydara FBX Binary  \x00\x1a\x00" + png_bytes

    textures = tmp_path / "Textures"
    saved = _extract_textures_from_fbx(fbx_bytes, textures)
    assert len(saved) == 1
    assert saved[0].name == "base_color.png"
    assert saved[0].read_bytes().startswith(b"\x89PNG")


def test_fake_higgsfield_writes_valid_png(tmp_path):
    from asset_assembly_automator.clients.concept_images import is_valid_image
    from asset_assembly_automator.clients.higgsfield_client import FakeHiggsfieldClient

    client = FakeHiggsfieldClient(tmp_path / "concept")
    result = __import__("asyncio").run(client.generate_image("test prompt"))
    path = result["results"][0]["local_path"]
    assert is_valid_image(path)


def test_resume_helpers(db):
    database, pipeline_id = db
    database.update_pipeline_stage(pipeline_id, StageId.MESHY_I2D.value, status="active")
    rows = find_resumable_pipelines(database)
    assert any(r["id"] == pipeline_id for r in rows)
    assert should_regenerate(None) is True
    assert should_regenerate({"status": "FAILED"}) is True
    assert should_regenerate({"status": "SUCCEEDED"}) is False
