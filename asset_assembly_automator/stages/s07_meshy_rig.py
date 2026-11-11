from __future__ import annotations

import asyncio

from asset_assembly_automator.clients.meshy_client import describe_task_failure
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import (
    get_meshy_client,
    job_metadata,
    mesh_source_for_pipeline,
    record_meshy_result,
    resolve_meshy_job,
    reusable_meshy_job,
    run_meshy_task,
    run_stage,
    stage_argparser,
)


async def _run(ctx, db, dirs, writer):
    settings = get_settings()
    pipe = db.get_pipeline(ctx.pipeline_id)
    remesh_id = pipe.metadata.get("remesh_task_id")
    source = mesh_source_for_pipeline(db, pipe)
    if remesh_id:
        input_task, input_source = str(remesh_id), "remesh"
    elif source:
        input_task, input_source = source["task_id"], source["task_type"]
        writer.log(
            "warning",
            f"Rigging from {input_source} without remesh",
            task_id=input_task,
        )
    else:
        return StageResult(success=False, stage=StageId.MESHY_RIG.value, error="No mesh task")

    face_count = pipe.metadata.get("face_count") or 0
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
        existing = reusable_meshy_job(db, ctx.pipeline_id, "rigging", force_new=ctx.force_new)
        if existing:
            existing_input = job_metadata(existing).get("input_task_id")
            # Legacy rows have no input recorded; keep reattaching to them.
            if existing_input not in (None, input_task):
                existing = None
        if existing:
            task_id = existing["task_id"]
            writer.log("info", "Reusing existing rig job", task_id=task_id)
            result = await resolve_meshy_job(
                client,
                task_id,
                "rigging",
                cancel_event=ctx.cancel_event,
                writer=writer,
                db=db,
                job_id=existing["id"],
            )
            record_meshy_result(db, existing["id"], result)
        else:
            result = await run_meshy_task(
                client,
                db,
                ctx,
                writer,
                task_type="rigging",
                metadata={"input_task_id": input_task, "input_task_type": input_source},
                create=lambda: client.rig(input_task, height_meters=height),
            )
            task_id = result["task_id"]

        if result.get("status") != "SUCCEEDED":
            return StageResult(
                success=False,
                stage=StageId.MESHY_RIG.value,
                error=f"Rig {describe_task_failure(result)}",
                data={"rig_task_id": task_id},
            )
        pipe.metadata["rig_task_id"] = task_id
        db.update_pipeline_stage(ctx.pipeline_id, StageId.MESHY_RIG.value, metadata=pipe.metadata)
        return StageResult(
            success=True,
            stage=StageId.MESHY_RIG.value,
            message="Rig complete (walk+run included)",
            next_stage=StageId.MESHY_ANIMATE.value,
            data={"rig_task_id": task_id},
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
