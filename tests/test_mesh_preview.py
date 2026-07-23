from pathlib import Path

import pytest
from asset_assembly_automator.clients.meshy_client import FakeMeshyClient, MeshyClient
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.mesh_preview import (
    cache_mesh_preview_from_i2d,
    ensure_mesh_preview,
)
from asset_assembly_automator.core.output_paths import (
    get_output_dirs_for,
    preview_glb_path,
    preview_png_path,
)
from PIL import Image


@pytest.fixture
def output_dirs(tmp_path):
    from asset_assembly_automator.core.db.models import Pipeline, Project

    project = Project(
        id=1,
        name="TestProject",
        pipeline_type="character",
        output_root=str(tmp_path / "out"),
        unity_project_path=None,
        created_at="",
    )
    pipe = Pipeline(
        id=1,
        project_id=1,
        asset_name="Hero",
        current_stage="draft",
        status="active",
        selected_concept_provider=None,
        selected_concept_asset_id=None,
        rig_provider="meshy",
        poly_budget="hero",
        multi_view=False,
        metadata={"character_slug": "hero"},
        created_at="",
        updated_at="",
    )
    return get_output_dirs_for(project, pipe), pipe


def test_default_meshy_i2d_formats():
    settings = get_settings()
    assert settings.meshy.i2d_target_formats == ["fbx", "glb"]
    assert settings.meshy.smart_topology == "auto"
    assert settings.meshy.remove_lighting is True


def test_preview_paths(output_dirs):
    dirs, pipe = output_dirs
    slug = pipe.metadata["character_slug"]
    assert preview_png_path(dirs, slug).name == "CHR_hero_mesh_preview.png"
    assert preview_glb_path(dirs).name == "Character_preview.glb"


@pytest.mark.asyncio
async def test_fake_download_i2d_preview_assets(output_dirs):
    dirs, _pipe = output_dirs
    client = FakeMeshyClient()
    created = await client.image_to_3d("fake.png")
    assets = await client.download_i2d_preview_assets(
        created["task_id"],
        previews_dir=dirs["previews"],
        source_dir=dirs["source"],
        textures_dir=dirs["textures"],
    )
    assert assets["thumbnail_path"]
    assert assets["glb_path"]
    assert Path(assets["thumbnail_path"]).is_file()
    assert Path(assets["glb_path"]).is_file()


@pytest.mark.asyncio
async def test_cache_mesh_preview_from_i2d(output_dirs):
    dirs, pipe = output_dirs
    client = FakeMeshyClient()
    created = await client.image_to_3d("fake.png")
    preview = await cache_mesh_preview_from_i2d(
        client,
        created["task_id"],
        dirs,
        pipe.metadata["character_slug"],
    )
    assert preview is not None
    assert preview.is_file()
    assert preview.name == "CHR_hero_mesh_preview.png"


def test_ensure_mesh_preview_from_metadata(output_dirs):
    dirs, pipe = output_dirs
    png = preview_png_path(dirs, pipe.metadata["character_slug"])
    png.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color=(120, 80, 40)).save(png)
    pipe.metadata["mesh_preview_path"] = str(png)
    resolved = ensure_mesh_preview(pipe, dirs)
    assert resolved == png


@pytest.mark.asyncio
async def test_image_to_3d_payload_includes_texture_flags(tmp_path, monkeypatch):
    image = tmp_path / "tpose.png"
    Image.new("RGB", (4, 4), color=(255, 0, 0)).save(image)

    captured: dict = {}

    async def fake_post(_path, payload):
        captured["payload"] = payload
        return {"task_id": "task-123", "status": "PENDING"}

    client = MeshyClient(api_key="test-key")
    monkeypatch.setattr(client, "_post", fake_post)

    settings = get_settings().meshy.model_dump()
    settings["target_formats"] = settings["i2d_target_formats"]
    await client.image_to_3d(str(image), settings=settings)

    payload = captured["payload"]
    assert payload["enable_pbr"] is True
    assert payload["hd_texture"] is True
    assert payload["remove_lighting"] is True
    assert "glb" in payload["target_formats"]
    assert "fbx" in payload["target_formats"]
