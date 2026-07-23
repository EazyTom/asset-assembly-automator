from __future__ import annotations

import asyncio

from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import (
    get_meshy_client,
    meshy_face_count,
    remesh_target_for_pipeline,
    resolve_meshy_job,
    run_stage,
    stage_argparser,
)


async def _run(ctx, db, dirs, writer):
    settings = get_settings()
    pipe = db.get_pipeline(ctx.pipeline_id)
    i2d_job = db.get_external_job(ctx.pipeline_id, "image-to-3d", active_only=False)
    if not i2d_job:
        return StageResult(success=False, stage=StageId.MESHY_REMESH.value, error="No i2d job")

    target = remesh_target_for_pipeline(pipe)
    client = get_meshy_client(ctx.dry_run)
    try:
        i2d_result = await resolve_meshy_job(
            client,
            i2d_job["task_id"],
            "image-to-3d",
            cancel_event=ctx.cancel_event,
            writer=writer,
        )
        i2d_status = i2d_result.get("status", "FAILED")
        source_face_count = meshy_face_count(i2d_result) or pipe.metadata.get("face_count") or 0
        db.update_external_job(
            i2d_job["id"],
            status=i2d_status,
            face_count=source_face_count or None,
        )
        if i2d_status != "SUCCEEDED":
            return StageResult(
                success=False,
                stage=StageId.MESHY_REMESH.value,
                error=(
                    f"Image-to-3D must finish before remesh (status={i2d_status}). "
                    "Wait for Meshy to finish, then run again."
                ),
                data={"i2d_task_id": i2d_job["task_id"], "i2d_status": i2d_status},
            )
        pipe.metadata["i2d_task_id"] = i2d_job["task_id"]
        if source_face_count:
            pipe.metadata["face_count"] = source_face_count

        if pipe.metadata.get("i2d_model_type") == "lowpoly":
            writer.log(
                "info",
                "Skipping remesh — i2d used lowpoly/smart topology model_type",
                i2d_task_id=i2d_job["task_id"],
            )
            db.update_pipeline_stage(
                ctx.pipeline_id, StageId.MESHY_REMESH.value, metadata=pipe.metadata
            )
            return StageResult(
                success=True,
                stage=StageId.MESHY_REMESH.value,
                message="Remesh skipped — i2d lowpoly output already game-ready",
                next_stage=StageId.MESHY_RIG.value,
                data={
                    "skipped": True,
                    "reason": "lowpoly_i2d",
                    "i2d_task_id": i2d_job["task_id"],
                },
            )

        writer.log(
            "info",
            "Remesh settings",
            poly_budget=pipe.poly_budget,
            source_face_count=source_face_count,
            target_polycount=target,
            topology=settings.meshy.topology,
            target_formats=settings.meshy.target_formats,
            i2d_task_id=i2d_job["task_id"],
        )

        if source_face_count and source_face_count <= target:
            writer.log(
                "info",
                "Skipping remesh — source mesh already within target polycount",
                source_face_count=source_face_count,
                target_polycount=target,
            )
            db.update_pipeline_stage(
                ctx.pipeline_id, StageId.MESHY_REMESH.value, metadata=pipe.metadata
            )
            return StageResult(
                success=True,
                stage=StageId.MESHY_REMESH.value,
                message=(
                    f"Remesh skipped — source {source_face_count:,} tris "
                    f"already at or below target {target:,}"
                ),
                next_stage=StageId.MESHY_RIG.value,
                data={
                    "skipped": True,
                    "source_face_count": source_face_count,
                    "target_polycount": target,
                    "i2d_task_id": i2d_job["task_id"],
                },
            )

        if not ctx.force_new:
            existing = db.get_external_job(ctx.pipeline_id, "remesh")
            if existing:
                task_id = existing["task_id"]
                writer.log("info", "Reusing existing remesh job", task_id=task_id)
                result = await resolve_meshy_job(
                    client,
                    task_id,
                    "remesh",
                    cancel_event=ctx.cancel_event,
                    writer=writer,
                )
                status = result.get("status", "FAILED")
                db.update_external_job(
                    existing["id"],
                    status=status,
                    face_count=target,
                )
                if status != "SUCCEEDED":
                    return StageResult(
                        success=False,
                        stage=StageId.MESHY_REMESH.value,
                        error=f"Remesh job failed: {status}",
                    )
                pipe.metadata["remesh_task_id"] = task_id
                pipe.metadata["face_count"] = target
                db.update_pipeline_stage(
                    ctx.pipeline_id, StageId.MESHY_REMESH.value, metadata=pipe.metadata
                )
                return StageResult(
                    success=True,
                    stage=StageId.MESHY_REMESH.value,
                    message=f"Remeshed to {target} tris",
                    next_stage=StageId.MESHY_RIG.value,
                    data={"task_id": task_id, "target_polycount": target},
                )

        created = await client.remesh(
            i2d_job["task_id"],
            target_polycount=target,
            topology=settings.meshy.topology,
            target_formats=settings.meshy.target_formats,
        )
        task_id = created["task_id"]
        job_id = db.save_external_job(ctx.pipeline_id, "meshy", task_id, "remesh")
        writer.log("info", "Remesh job created", task_id=task_id, target_polycount=target)
        result = await client.poll_until_done(task_id, "remesh", cancel_event=ctx.cancel_event)
        status = result.get("status", "FAILED")
        db.update_external_job(job_id, status=status, face_count=target)
        pipe.metadata["remesh_task_id"] = task_id
        pipe.metadata["face_count"] = target
        db.update_pipeline_stage(
            ctx.pipeline_id, StageId.MESHY_REMESH.value, metadata=pipe.metadata
        )
        return StageResult(
            success=status == "SUCCEEDED",
            stage=StageId.MESHY_REMESH.value,
            message=f"Remeshed to {target} tris",
            next_stage=StageId.MESHY_RIG.value,
            data={"task_id": task_id, "target_polycount": target},
            error=None if status == "SUCCEEDED" else f"Remesh failed: {status}",
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
        StageId.MESHY_REMESH.value,
        _run,
        dry_run=dry_run,
        verbose=verbose,
        force_new=force_new,
    )


if __name__ == "__main__":
    args = stage_argparser("Meshy remesh to budget").parse_args()
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
