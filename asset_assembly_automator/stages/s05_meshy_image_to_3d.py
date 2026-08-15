from __future__ import annotations

import asyncio
from pathlib import Path

from asset_assembly_automator.clients.image_prep import (
    ensure_i2d_upload_image,
    select_tpose_source,
)
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.mesh_preview import cache_mesh_preview_from_i2d
from asset_assembly_automator.core.output_paths import pipeline_character_slug, preview_glb_path
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import (
    get_meshy_client,
    meshy_face_count,
    meshy_settings_for_pipeline,
    resolve_meshy_job,
    run_stage,
    stage_argparser,
)


async def _complete_i2d_job(
    ctx,
    db,
    dirs,
    pipe,
    client,
    writer,
    *,
    task_id: str,
    job_row_id: int,
):
    result = await resolve_meshy_job(
        client,
        task_id,
        "image-to-3d",
        cancel_event=ctx.cancel_event,
        writer=writer,
    )
    status = result.get("status", "FAILED")
    face_count = meshy_face_count(result)
    db.update_external_job(job_row_id, status=status, face_count=face_count)
    pipe.metadata["i2d_task_id"] = task_id
    if face_count is not None:
        pipe.metadata["face_count"] = face_count
    if status != "SUCCEEDED":
        db.update_pipeline_stage(ctx.pipeline_id, StageId.MESHY_I2D.value, metadata=pipe.metadata)
        return StageResult(
            success=False,
            stage=StageId.MESHY_I2D.value,
            error=f"Image-to-3D job not ready: {status}",
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
    nested = result.get("result") or {}
    thumb_url = result.get("thumbnail_url") or nested.get("thumbnail_url")
    if thumb_url:
        pipe.metadata["i2d_thumbnail_url"] = thumb_url

    db.update_pipeline_stage(ctx.pipeline_id, StageId.MESHY_I2D.value, metadata=pipe.metadata)
    return StageResult(
        success=True,
        stage=StageId.MESHY_I2D.value,
        message=f"Image-to-3D complete face_count={face_count}",
        next_stage=StageId.MESHY_REMESH.value,
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
        if not ctx.force_new:
            existing = db.get_external_job(ctx.pipeline_id, "image-to-3d", active_only=False)
            if existing:
                writer.log(
                    "info",
                    "Reusing existing i2d job",
                    task_id=existing["task_id"],
                    status=existing.get("status"),
                )
                return await _complete_i2d_job(
                    ctx,
                    db,
                    dirs,
                    pipe,
                    client,
                    writer,
                    task_id=existing["task_id"],
                    job_row_id=existing["id"],
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
        ai_model = str(cfg.get("ai_model", "latest"))
        if (cfg.get("hd_texture") or cfg.get("remove_lighting")) and ai_model not in (
            "latest",
            "meshy-6",
        ):
            writer.log(
                "warning",
                "hd_texture and remove_lighting require ai_model latest or meshy-6",
                ai_model=ai_model,
            )
        writer.log(
            "info",
            "Image-to-3D settings",
            poly_budget=pipe.poly_budget,
            smart_topology=cfg.get("smart_topology"),
            target_polycount=cfg["target_polycount"],
            ai_model=cfg.get("ai_model"),
            model_type=cfg.get("model_type"),
            target_formats=cfg.get("target_formats"),
            enable_pbr=cfg.get("enable_pbr"),
            should_texture=cfg.get("should_texture"),
            hd_texture=cfg.get("hd_texture"),
            remove_lighting=cfg.get("remove_lighting"),
            image_enhancement=cfg.get("image_enhancement"),
        )
        if cfg.get("model_type") == "lowpoly":
            writer.log(
                "info",
                "lowpoly model_type ignores topology, target_polycount, and inline remesh params",
            )
        created = await client.image_to_3d(
            image_path,
            texture_prompt=meshy_prompt or None if not texture_image_path else None,
            texture_image_path=texture_image_path,
            multi_view_paths=multi_paths if pipe.multi_view and multi_paths else None,
            settings=cfg,
        )
        task_id = created["task_id"]
        job_id = db.save_external_job(ctx.pipeline_id, "meshy", task_id, "image-to-3d")
        writer.log("info", "Image-to-3D job created", task_id=task_id)
        return await _complete_i2d_job(
            ctx,
            db,
            dirs,
            pipe,
            client,
            writer,
            task_id=task_id,
            job_row_id=job_id,
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
