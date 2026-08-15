from __future__ import annotations

import asyncio

from asset_assembly_automator.clients.image_prep import select_tpose_source
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.output_paths import approved_concept_path, pipeline_output_slug
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import get_magnific_client, run_stage, stage_argparser


async def _run(ctx, db, dirs, writer):
    pipe = db.get_pipeline(ctx.pipeline_id)
    if not pipe:
        return StageResult(
            success=False, stage=StageId.MAGNIFIC_UPREZ.value, error="Pipeline not found"
        )

    settings = get_settings()
    meta = pipe.metadata or {}
    if not meta.get("magnific_enabled", settings.magnific.default_enabled):
        writer.log(
            "info",
            "Magnific uprez skipped",
            skipped=True,
            reason="magnific_disabled",
        )
        return StageResult(
            success=True,
            stage=StageId.MAGNIFIC_UPREZ.value,
            message="Magnific uprez skipped (disabled)",
            next_stage=StageId.IMAGE_PREP.value,
            data={"skipped": True, "reason": "magnific_disabled"},
        )

    if meta.get("magnific_already_applied"):
        writer.log(
            "info",
            "Magnific uprez skipped — already applied before approval",
            skipped=True,
            reason="already_applied",
        )
        return StageResult(
            success=True,
            stage=StageId.MAGNIFIC_UPREZ.value,
            message="Magnific uprez skipped (already applied)",
            next_stage=StageId.IMAGE_PREP.value,
            data={"skipped": True, "reason": "already_applied"},
        )

    assets = db.get_assets(ctx.pipeline_id, "tpose")
    if not assets:
        assets = db.get_assets(ctx.pipeline_id, "concept")
    source_path = select_tpose_source(assets)
    if not source_path:
        return StageResult(
            success=False,
            stage=StageId.MAGNIFIC_UPREZ.value,
            error="No approved concept image for Magnific uprez",
        )
    output_slug = pipeline_output_slug(pipe)
    approved_path = approved_concept_path(dirs, output_slug, pipe.asset_kind)
    approved_path.parent.mkdir(parents=True, exist_ok=True)

    if meta.get("magnific_output_path") == str(approved_path) and approved_path.is_file():
        writer.log(
            "info",
            "Magnific uprez skipped — output already present",
            skipped=True,
            reason="already_uprezzed",
            path=str(approved_path),
        )
        return StageResult(
            success=True,
            stage=StageId.MAGNIFIC_UPREZ.value,
            message="Magnific output already present",
            next_stage=StageId.IMAGE_PREP.value,
            data={"skipped": True, "path": str(approved_path)},
        )

    mode = str(meta.get("magnific_upscale_mode") or settings.magnific.upscale_mode)
    scale = str(meta.get("magnific_upscale_scale_factor") or settings.magnific.upscale_scale_factor)
    flavor = str(meta.get("magnific_upscale_flavor") or settings.magnific.upscale_flavor)
    client = get_magnific_client(ctx.dry_run, dirs["concept"])
    try:
        writer.log(
            "info",
            "Starting Magnific upscale",
            provider="magnific",
            mode=mode,
            scale_factor=scale,
        )
        result = await client.upscale_image(
            source_path,
            scale_factor=scale,
            mode=mode,  # type: ignore[arg-type]
            flavor=flavor,
        )
        local_path = result.get("local_path")
        if not local_path:
            return StageResult(
                success=False,
                stage=StageId.MAGNIFIC_UPREZ.value,
                error="Magnific upscale returned no local_path",
            )

        from shutil import copy2

        copy2(local_path, approved_path)
        task_id = str(result.get("id") or "")
        if task_id:
            db.save_external_job(
                ctx.pipeline_id,
                "magnific",
                task_id,
                "upscale",
                status="SUCCEEDED",
            )
            writer.log("info", "Magnific job complete", provider="magnific", task_id=task_id)

        db.add_asset(
            ctx.pipeline_id,
            "tpose",
            str(approved_path),
            provider="magnific",
            metadata={"source": source_path, "task_id": task_id},
        )
        db.update_pipeline_stage(
            ctx.pipeline_id,
            StageId.MAGNIFIC_UPREZ.value,
            metadata={
                **meta,
                "magnific_output_path": str(approved_path),
                "magnific_task_id": task_id,
            },
        )
        return StageResult(
            success=True,
            stage=StageId.MAGNIFIC_UPREZ.value,
            message=f"Magnific uprez saved to {approved_path.name}",
            next_stage=StageId.IMAGE_PREP.value,
            data={"path": str(approved_path), "task_id": task_id},
        )
    finally:
        if hasattr(client, "close"):
            await client.close()


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id,
        StageId.MAGNIFIC_UPREZ.value,
        _run,
        dry_run=dry_run,
        verbose=verbose,
    )


if __name__ == "__main__":
    args = stage_argparser("Magnific concept uprez").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
