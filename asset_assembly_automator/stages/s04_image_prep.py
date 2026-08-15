from __future__ import annotations

import asyncio
from pathlib import Path

from asset_assembly_automator.clients.image_prep import (
    crop_with_padding,
    downscale_to_budget,
    select_tpose_source,
    validate_tpose_checklist,
)
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import run_stage, stage_argparser


async def _run(ctx, db, dirs, writer):
    assets = db.get_assets(ctx.pipeline_id, "tpose")
    src = select_tpose_source(assets)
    if not src:
        return StageResult(
            success=False, stage=StageId.IMAGE_PREP.value, error="No approved T-pose"
        )
    cropped = dirs["tpose"] / f"{Path(src).stem}_cropped.png"
    crop_with_padding(src, str(cropped))
    out = dirs["tpose"] / f"{Path(src).stem}_prepped.png"
    settings = get_settings()
    prep_meta = downscale_to_budget(
        str(cropped),
        str(out),
        max_px=settings.meshy.i2d_max_image_px,
        max_bytes=settings.meshy.i2d_max_image_mb * 1024 * 1024,
    )
    prepped_path = str(prep_meta.get("path") or out)
    writer.log(
        "info",
        "Image prep resize",
        **prep_meta,
        meshy_ui_limit_mb=20,
    )
    checklist = validate_tpose_checklist(prepped_path)
    writer.log("info", "T-pose checklist", **checklist)
    asset_meta = {**checklist, **prep_meta}
    db.add_asset(ctx.pipeline_id, "tpose", prepped_path, metadata=asset_meta)
    pipe = db.get_pipeline(ctx.pipeline_id)
    if pipe and prep_meta.get("downscaled"):
        meta = {
            **pipe.metadata,
            "hires_texture_path": str(cropped),
        }
        db.update_pipeline_stage(ctx.pipeline_id, pipe.current_stage, metadata=meta)
        writer.log("info", "Stored hi-res texture source", path=str(cropped))
    return StageResult(
        success=True,
        stage=StageId.IMAGE_PREP.value,
        message=f"Image prepped score={checklist['score']}/{checklist['max']}",
        next_stage=StageId.MESHY_I2D.value,
        data={"path": prepped_path, "checklist": checklist},
    )


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.IMAGE_PREP.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    args = stage_argparser("Prep approved image").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
