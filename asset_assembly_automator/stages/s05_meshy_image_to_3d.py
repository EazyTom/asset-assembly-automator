from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from asset_assembly_automator.clients.image_prep import (
    ensure_i2d_upload_image,
    select_tpose_source,
)
from asset_assembly_automator.clients.meshy_client import describe_task_failure, task_output
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.mesh_preview import cache_mesh_preview_from_i2d
from asset_assembly_automator.core.output_paths import pipeline_character_slug, preview_glb_path
from asset_assembly_automator.core.state_machine import StageId, mesh_review_enabled
from asset_assembly_automator.stages._base import (
    get_meshy_client,
    meshy_face_count,
    meshy_settings_for_pipeline,
    record_meshy_result,
    resolve_meshy_job,
    reusable_meshy_job,
    run_meshy_task,
    run_stage,
    stage_argparser,
)


async def _finish_i2d(
    ctx,
    db,
    dirs,
    pipe,
    client,
    writer,
    *,
    task_id: str,
    job_row_id: int,
    result: dict[str, Any],
):
    status = result.get("status", "FAILED")
    face_count = meshy_face_count(result)
    if face_count is not None:
        db.update_external_job(job_row_id, face_count=face_count)
        pipe.metadata["face_count"] = face_count
    pipe.metadata["i2d_task_id"] = task_id
    if status != "SUCCEEDED":
        db.update_pipeline_stage(ctx.pipeline_id, StageId.MESHY_I2D.value, metadata=pipe.metadata)
        return StageResult(
            success=False,
            stage=StageId.MESHY_I2D.value,
            error=f"Image-to-3D {describe_task_failure(result)}",
            data={"task_id": task_id, "status": status},
        )

    slug = pipeline_character_slug(pipe)
    preview_path = await cache_mesh_preview_from_i2d(
        client,
        task_id,
        dirs,
        slug,
        writer=writer,
    )
    if preview_path:
        pipe.metadata["mesh_preview_path"] = str(preview_path)
    glb_path = preview_glb_path(dirs)
    if glb_path.is_file():
        pipe.metadata["preview_glb_path"] = str(glb_path)
    thumb_url = task_output(result).get("thumbnail_url") or result.get("thumbnail_url")
    if thumb_url:
        pipe.metadata["i2d_thumbnail_url"] = thumb_url

    review = mesh_review_enabled(pipe)
    db.update_pipeline_stage(ctx.pipeline_id, StageId.MESHY_I2D.value, metadata=pipe.metadata)
    return StageResult(
        success=True,
        stage=StageId.MESHY_I2D.value,
        message=f"Image-to-3D complete face_count={face_count}"
        + (" — waiting for mesh review" if review else ""),
        next_stage=(StageId.MESH_REVIEW if review else StageId.MESHY_REMESH).value,
        data={
            "task_id": task_id,
            "face_count": face_count,
            "status": status,
            "mesh_preview_path": pipe.metadata.get("mesh_preview_path"),
        },
    )


async def _run(ctx, db, dirs, writer):
    pipe = db.get_pipeline(ctx.pipeline_id)
    client = get_meshy_client(ctx.dry_run)
    try:
        existing = reusable_meshy_job(db, ctx.pipeline_id, "image-to-3d", force_new=ctx.force_new)
        if existing:
            writer.log(
                "info",
                "Reusing existing i2d job",
                task_id=existing["task_id"],
                status=existing.get("status"),
            )
            result = await resolve_meshy_job(
                client,
                existing["task_id"],
                "image-to-3d",
                cancel_event=ctx.cancel_event,
                writer=writer,
                db=db,
                job_id=existing["id"],
            )
            record_meshy_result(db, existing["id"], result)
            return await _finish_i2d(
                ctx,
                db,
                dirs,
                pipe,
                client,
                writer,
                task_id=existing["task_id"],
                job_row_id=existing["id"],
                result=result,
            )

        tpose = db.get_assets(ctx.pipeline_id, "tpose")
        image_path = select_tpose_source(tpose, prefer_prepped=True)
        if not image_path:
            return StageResult(
                success=False, stage=StageId.MESHY_I2D.value, error="No T-pose asset"
            )
        settings = get_settings()
        cap_dest = dirs["tpose"] / f"{Path(image_path).stem}_i2dcap.png"
        cap_meta = ensure_i2d_upload_image(
            image_path,
            str(cap_dest),
            max_px=settings.meshy.i2d_max_image_px,
            max_mb=settings.meshy.i2d_max_image_mb,
        )
        if cap_meta.get("downscaled"):
            writer.log("info", "Resized image for Meshy 20MB i2d limit", **cap_meta)
            image_path = str(cap_meta["path"])
        meshy_prompt = pipe.metadata.get("meshy_texture_prompt", "")
        multi_paths = pipe.metadata.get("turnaround_paths")

        cfg = meshy_settings_for_pipeline(pipe)
        texture_image_path = None
        if cfg.get("use_hires_texture_image"):
            hires = pipe.metadata.get("hires_texture_path")
            if hires and Path(hires).is_file():
                texture_image_path = hires
                writer.log("info", "Using hi-res texture image", path=hires)
        pipe.metadata["i2d_model_type"] = cfg.get("model_type")
        # A new base mesh invalidates any variant approved for the previous one.
        pipe.metadata.pop("mesh_source", None)
        db.update_pipeline_metadata(ctx.pipeline_id, remove_keys=("mesh_source",))
        writer.log(
            "info",
            "Image-to-3D settings",
            poly_budget=pipe.poly_budget,
            smart_topology=cfg.get("smart_topology"),
            target_polycount=cfg["target_polycount"],
            ai_model=cfg.get("ai_model"),
            model_type=cfg.get("model_type"),
            geometry_resolution=cfg.get("geometry_resolution"),
            texture_resolution=cfg.get("texture_resolution"),
            target_formats=cfg.get("target_formats"),
            enable_pbr=cfg.get("enable_pbr"),
            should_texture=cfg.get("should_texture"),
            remove_lighting=cfg.get("remove_lighting"),
            image_enhancement=cfg.get("image_enhancement"),
        )
        result = await run_meshy_task(
            client,
            db,
            ctx,
            writer,
            task_type="image-to-3d",
            create=lambda: client.image_to_3d(
                image_path,
                texture_prompt=meshy_prompt or None if not texture_image_path else None,
                texture_image_path=texture_image_path,
                multi_view_paths=multi_paths if pipe.multi_view and multi_paths else None,
                settings=cfg,
            ),
        )
        return await _finish_i2d(
            ctx,
            db,
            dirs,
            pipe,
            client,
            writer,
            task_id=result["task_id"],
            job_row_id=result["job_id"],
            result=result,
        )
    finally:
        if hasattr(client, "close"):
            await client.close()


async def run(
    pipeline_id: int,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    force_new: bool = False,
    **kwargs,
):
    return await run_stage(
        pipeline_id,
        StageId.MESHY_I2D.value,
        _run,
        dry_run=dry_run,
        verbose=verbose,
        force_new=force_new,
    )


if __name__ == "__main__":
    args = stage_argparser("Meshy image to 3D").parse_args()
    print(
        asyncio.run(
            run(
                args.pipeline_id,
                dry_run=args.dry_run,
                verbose=args.verbose,
                force_new=args.force_new,
            )
        )
    )
