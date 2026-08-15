from __future__ import annotations

from pathlib import Path

import pytest
from asset_assembly_automator.clients.image_prep import downscale_to_budget
from asset_assembly_automator.clients.magnific_client import (
    FakeMagnificClient,
    _parse_scale_factor,
    create_magnific_client,
)
from asset_assembly_automator.core.secrets import _parse_magnific_key_file
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.gui.widgets.pipeline_stepper import stage_display_label


def test_parse_scale_factor_accepts_suffix():
    assert _parse_scale_factor("4x") == 4
    assert _parse_scale_factor(8) == 8


def test_parse_magnific_key_file_reads_labeled_key(tmp_path: Path):
    key_file = tmp_path / "magnific-api.key"
    key_file.write_text(
        "Magnific.com API Key:\nMS_test_key_12345\n\nMagnific.com Webhook Signing Secret:\nsecret\n",
        encoding="utf-8",
    )
    assert _parse_magnific_key_file(key_file) == "MS_test_key_12345"


@pytest.mark.asyncio
async def test_fake_magnific_generate_writes_png(tmp_path: Path):
    client = FakeMagnificClient(tmp_path)
    result = await client.generate_image("test prompt")
    path = Path(result["results"][0]["local_path"])
    assert path.is_file()
    assert path.stat().st_size > 64


@pytest.mark.asyncio
async def test_fake_magnific_upscale_writes_png(tmp_path: Path):
    client = FakeMagnificClient(tmp_path)
    source = tmp_path / "source.png"
    source.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    result = await client.upscale_image(str(source), scale_factor="2x", mode="precision_v2")
    path = Path(result["local_path"])
    assert path.is_file()


def test_create_magnific_client_dry_run(tmp_path: Path):
    client = create_magnific_client(True, tmp_path)
    assert isinstance(client, FakeMagnificClient)


def test_downscale_to_budget_resizes_large_image(tmp_path: Path):
    from PIL import Image

    src = tmp_path / "large.png"
    Image.new("RGB", (4096, 6144), color=(200, 100, 50)).save(src)
    dest = tmp_path / "small.png"
    meta = downscale_to_budget(str(src), str(dest), max_px=2048, max_bytes=18 * 1024 * 1024)
    assert meta["downscaled"] is True
    assert meta["final_width"] <= 2048
    assert meta["final_height"] <= 3072
    assert Path(meta["path"]).stat().st_size <= 18 * 1024 * 1024


def test_downscale_to_budget_respects_byte_limit(tmp_path: Path):
    import os

    from asset_assembly_automator.clients.image_prep import MESHY_I2D_HARD_LIMIT_BYTES
    from PIL import Image

    src = tmp_path / "noise.png"
    w, h = 1200, 1200
    Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)).save(src, format="PNG")
    dest = tmp_path / "capped.png"
    meta = downscale_to_budget(str(src), str(dest), max_px=8192, max_bytes=250_000)
    assert Path(meta["path"]).stat().st_size <= 250_000
    assert meta["final_bytes"] <= 250_000
    assert meta["final_bytes"] <= MESHY_I2D_HARD_LIMIT_BYTES


def test_select_tpose_source_prefers_native_then_prepped():
    from asset_assembly_automator.clients.image_prep import select_tpose_source

    assets = [
        {"file_path": r"C:\out\hero_prepped.png"},
        {"file_path": r"C:\out\hero_cropped.png"},
        {"file_path": r"C:\out\hero_approved.png"},
    ]
    assert select_tpose_source(assets) == r"C:\out\hero_approved.png"
    assert select_tpose_source(assets, prefer_prepped=True) == r"C:\out\hero_prepped.png"


def test_stage_display_label_concept_image():
    assert stage_display_label(StageId.IMAGE_PREP) == "Image Prep"
    assert stage_display_label(StageId.MAGNIFIC_UPREZ) == "Magnific Uprez"
