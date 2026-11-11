from __future__ import annotations

import asyncio

from asset_assembly_automator.clients.meshy_client import describe_task_failure
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId, asset_kind_for_pipeline
from asset_assembly_automator.stages._base import (
    get_meshy_client,
    job_metadata,
    mesh_source_for_pipeline,
    meshy_face_count,
    record_meshy_result,
    remesh_target_for_pipeline,
    resolve_meshy_job,
    reusable_meshy_job,
    run_meshy_task,
    run_stage,
    stage_argparser,
)


def _skip(db, ctx, pipe, *, message: str, next_stage: str, **data) -> StageResult:
    # Drop a remesh from an earlier run so rig/download use the current mesh source.
    pipe.metadata.pop("remesh_task_id", None)
    db.update_pipeline_stage(
        ctx.pipeline_id,
        StageId.MESHY_REMESH.value,
        metadata=pipe.metadata,
        remove_metadata_keys=("remesh_task_id",),
    )
    return StageResult(
        success=True,
        stage=StageId.MESHY_REMESH.value,
        message=message,
        next_stage=next_stage,
        data={"skipped": True, **data},
    )


async def _run(ctx, db, dirs, writer):
    settings = get_settings()
    pipe = db.get_pipeline(ctx.pipeline_id)
    kind = asset_kind_for_pipeline(pipe)
    next_after_remesh = (
        StageId.MESHY_RIG.value if kind == "character" else StageId.MESHY_DOWNLOAD.value
    )

    if not pipe.metadata.get("remesh_enabled", False):
        writer.log(
            "info",
            "Remesh skipped — disabled for pipeline",
            skipped=True,
            reason="remesh_disabled",
        )
        return _skip(
            db,
            ctx,
            pipe,
            message="Remesh skipped (disabled)",
            next_stage=next_after_remesh,
            reason="remesh_disabled",
        )

    if pipe.metadata.get("meshy_preset") == "game_ready":
        writer.log(
            "info",
            "Remesh skipped — game-ready smart topology preset",
            skipped=True,
            reason="smart_topology",
        )
        return _skip(
            db,
            ctx,
            pipe,
            message="Remesh skipped — smart-topology preset",
            next_stage=next_after_remesh,
            reason="smart_topology",
        )

    source = mesh_source_for_pipeline(db, pipe)
    if not source:
        return StageResult(success=False, stage=StageId.MESHY_REMESH.value, error="No i2d job")
    source_id, source_type = source["task_id"], source["task_type"]

    target = remesh_target_for_pipeline(pipe)
    client = get_meshy_client(ctx.dry_run)
    try:
        source_result = await resolve_meshy_job(
            client,
            source_id,
            source_type,
            cancel_event=ctx.cancel_event,
            writer=writer,
        )
        source_status = source_result.get("status", "FAILED")
        source_job = next(
            (
                j
                for j in db.list_external_jobs(ctx.pipeline_id, [source_type])
                if j["task_id"] == source_id
            ),
            None,
        )
        source_face_count = (
            meshy_face_count(source_result)
            or (source_job or {}).get("face_count")
            or pipe.metadata.get("face_count")
            or 0
        )
        if source_job:
            record_meshy_result(
                db, source_job["id"], source_result, face_count=source_face_count or None
            )
        if source_status != "SUCCEEDED":
            return StageResult(
                success=False,
                stage=StageId.MESHY_REMESH.value,
                error=(
                    f"{source_type} {source_id} must finish before remesh "
                    f"(status={source_status}). Wait for Meshy to finish, then run again."
                ),
                data={"source_task_id": source_id, "source_status": source_status},
            )
        if source_type == "image-to-3d":
            pipe.metadata["i2d_task_id"] = source_id
        if source_face_count:
            pipe.metadata["face_count"] = source_face_count

        writer.log(
            "info",
            "Remesh settings",
            poly_budget=pipe.poly_budget,
            source_face_count=source_face_count,
            target_polycount=target,
            topology=settings.meshy.topology,
            target_formats=settings.meshy.target_formats,
            source_task_id=source_id,
            source_task_type=source_type,
        )

        if source_face_count and source_face_count <= target:
            writer.log(
                "info",
                "Skipping remesh — source mesh already within target polycount",
                source_face_count=source_face_count,
                target_polycount=target,
            )
            return _skip(
                db,
                ctx,
                pipe,
                message=(
                    f"Remesh skipped — source {source_face_count:,} tris "
                    f"already at or below target {target:,}"
                ),
                next_stage=next_after_remesh,
                source_face_count=source_face_count,
                target_polycount=target,
                source_task_id=source_id,
            )

        existing = reusable_meshy_job(db, ctx.pipeline_id, "remesh", force_new=ctx.force_new)
        if existing:
            existing_input = job_metadata(existing).get("input_task_id")
            # Legacy rows have no input recorded; they were always remeshes of the i2d mesh.
            if existing_input != source_id and not (
                existing_input is None and source_type == "image-to-3d"
            ):
                existing = None
        if existing:
            task_id = existing["task_id"]
            writer.log("info", "Reusing existing remesh job", task_id=task_id)
            result = await resolve_meshy_job(
                client,
                task_id,
                "remesh",
                cancel_event=ctx.cancel_event,
                writer=writer,
                db=db,
                job_id=existing["id"],
            )
            record_meshy_result(db, existing["id"], result, face_count=target)
        else:
            result = await run_meshy_task(
                client,
                db,
                ctx,
                writer,
                task_type="remesh",
                metadata={"input_task_id": source_id, "input_task_type": source_type},
                create=lambda: client.remesh(
                    source_id,
                    target_polycount=target,
                    topology=settings.meshy.topology,
                    target_formats=settings.meshy.target_formats,
                ),
            )
            task_id = result["task_id"]
            db.update_external_job(result["job_id"], face_count=target)

        if result.get("status") != "SUCCEEDED":
            return StageResult(
                success=False,
                stage=StageId.MESHY_REMESH.value,
                error=f"Remesh {describe_task_failure(result)}",
                data={"task_id": task_id},
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
            next_stage=next_after_remesh,
            data={"task_id": task_id, "target_polycount": target, "source_task_id": source_id},
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
