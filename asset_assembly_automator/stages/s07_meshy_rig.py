from __future__ import annotations

import asyncio

from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import (
    get_meshy_client,
    resolve_meshy_job,
    run_stage,
    stage_argparser,
)


async def _run(ctx, db, dirs, writer):
    settings = get_settings()
    pipe = db.get_pipeline(ctx.pipeline_id)
    remesh = db.get_external_job(ctx.pipeline_id, "remesh", active_only=False)
    i2d = db.get_external_job(ctx.pipeline_id, "image-to-3d", active_only=False)
    input_task = (remesh or i2d or {}).get("task_id")
    if not input_task:
        return StageResult(success=False, stage=StageId.MESHY_RIG.value, error="No mesh task")

    if remesh:
        input_source = "remesh"
    else:
        input_source = "image-to-3d"
        writer.log(
            "warning",
            "Rigging from image-to-3d without remesh",
            task_id=input_task,
        )

    face_count = pipe.metadata.get("face_count") or (remesh or i2d or {}).get("face_count") or 0
    if face_count and face_count > settings.meshy.hard_rig_face_limit:
        return StageResult(
            success=False,
            stage=StageId.MESHY_RIG.value,
            error=(
                f"Face count {face_count} exceeds rig limit "
                f"{settings.meshy.hard_rig_face_limit}; remesh required"
            ),
        )

    height = settings.meshy.rig_height_meters
    writer.log(
        "info",
        "Rig settings",
        input_task_id=input_task,
        input_source=input_source,
        height_meters=height,
        face_count=face_count,
        basic_animations="walk+run included",
    )

    client = get_meshy_client(ctx.dry_run)
    try:
        if not ctx.force_new:
            existing = db.get_external_job(ctx.pipeline_id, "rigging")
            if existing:
                task_id = existing["task_id"]
                writer.log("info", "Reusing existing rig job", task_id=task_id)
                result = await resolve_meshy_job(
                    client,
                    task_id,
                    "rigging",
                    cancel_event=ctx.cancel_event,
                    writer=writer,
                )
                status = result.get("status", "FAILED")
                db.update_external_job(existing["id"], status=status)
                if status != "SUCCEEDED":
                    return StageResult(
                        success=False,
                        stage=StageId.MESHY_RIG.value,
                        error=f"Rig job failed: {status}",
                    )
                pipe.metadata["rig_task_id"] = task_id
                db.update_pipeline_stage(
                    ctx.pipeline_id, StageId.MESHY_RIG.value, metadata=pipe.metadata
                )
                return StageResult(
                    success=True,
                    stage=StageId.MESHY_RIG.value,
                    message="Rig complete (walk+run included)",
                    next_stage=StageId.MESHY_ANIMATE.value,
                    data={"rig_task_id": task_id},
                )

        created = await client.rig(input_task, height_meters=height)
        task_id = created["task_id"]
        job_id = db.save_external_job(ctx.pipeline_id, "meshy", task_id, "rigging")
        writer.log("info", "Rig job created", task_id=task_id)
        result = await client.poll_until_done(task_id, "rigging", cancel_event=ctx.cancel_event)
        status = result.get("status", "FAILED")
        db.update_external_job(job_id, status=status, credits_used=5)
        pipe.metadata["rig_task_id"] = task_id
        db.update_pipeline_stage(ctx.pipeline_id, StageId.MESHY_RIG.value, metadata=pipe.metadata)
        return StageResult(
            success=status == "SUCCEEDED",
            stage=StageId.MESHY_RIG.value,
            message="Rig complete (walk+run included)",
            next_stage=StageId.MESHY_ANIMATE.value,
            data={"rig_task_id": task_id},
            error=None if status == "SUCCEEDED" else f"Rig failed: {status}",
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
        StageId.MESHY_RIG.value,
        _run,
        dry_run=dry_run,
        verbose=verbose,
        force_new=force_new,
    )


if __name__ == "__main__":
    args = stage_argparser("Meshy rig character").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
