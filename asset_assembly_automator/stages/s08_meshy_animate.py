from __future__ import annotations

import asyncio

import httpx

from asset_assembly_automator.clients.animation_catalog import AnimationCatalog
from asset_assembly_automator.clients.meshy_client import describe_task_failure
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import (
    get_meshy_client,
    record_meshy_result,
    resolve_meshy_job,
    run_meshy_task,
    run_stage,
    stage_argparser,
)

# Stable Meshy library IDs for the default idles; used in dry-run and when the catalog
# cannot be fetched.
KNOWN_IDLE_ACTIONS = {
    "idle3": {"action_id": 243, "action_name": "Idle 3"},
    "idle4": {"action_id": 244, "action_name": "Idle 4"},
    "idle12": {"action_id": 252, "action_name": "Idle 12"},
}


def _idle_query_names(settings) -> list[str]:
    names = [str(n).strip() for n in settings.meshy.default_custom_animations if str(n).strip()]
    return names or ["idle3", "idle4", "idle12"]


def _known_selections(names: list[str]) -> list[dict]:
    return [dict(KNOWN_IDLE_ACTIONS[n.lower()]) for n in names if n.lower() in KNOWN_IDLE_ACTIONS]


async def _resolve_idle_selections(settings, *, dry_run: bool, writer) -> list[dict]:
    names = _idle_query_names(settings)
    if dry_run:
        return _known_selections(names)
    catalog = AnimationCatalog()
    try:
        await catalog.sync()
    except httpx.HTTPError as exc:
        writer.log("warning", "Meshy animation library unavailable", error=str(exc))
    selections = catalog.resolve(names)
    resolved = {s["action_name"] for s in selections}
    if len(selections) < len(names):
        for fallback in _known_selections(names):
            if fallback["action_name"] not in resolved:
                selections.append(fallback)
    return selections


def _reusable_animation_job(jobs: list[dict], rig_task_id: str, action_id: int) -> dict | None:
    for job in reversed(jobs):
        meta = job.get("metadata") or {}
        if (
            job.get("status") not in ("FAILED", "CANCELED")
            and meta.get("rig_task_id") == rig_task_id
            and meta.get("action_id") == action_id
        ):
            return job
    return None


async def _run(ctx, db, dirs, writer):
    settings = get_settings()
    pipe = db.get_pipeline(ctx.pipeline_id)
    rig_task_id = pipe.metadata.get("rig_task_id")
    if not rig_task_id:
        job = db.get_external_job(ctx.pipeline_id, "rigging", active_only=False)
        rig_task_id = job["task_id"] if job else None
    if not rig_task_id:
        return StageResult(success=False, stage=StageId.MESHY_ANIMATE.value, error="No rig task")
    rig_task_id = str(rig_task_id)

    selections = db.get_animation_selections(ctx.pipeline_id)
    if not selections:
        selections = await _resolve_idle_selections(settings, dry_run=ctx.dry_run, writer=writer)
        db.set_animation_selections(
            ctx.pipeline_id, [s for s in selections if s.get("action_id", -1) >= 0]
        )
        selections = db.get_animation_selections(ctx.pipeline_id)

    if not selections:
        return StageResult(
            success=False,
            stage=StageId.MESHY_ANIMATE.value,
            error="Could not resolve idle3, idle4, idle12 from Meshy animation catalog",
        )

    writer.log(
        "info",
        "Applying standard Meshy idle animations",
        idle_count=len(selections),
        idles=[s.get("action_name") for s in selections],
    )

    client = get_meshy_client(ctx.dry_run)
    previous = [] if ctx.force_new else db.list_external_jobs(ctx.pipeline_id, ["animation"])
    anim_tasks: list[str] = []
    anim_clips: list[dict] = []
    runnable = []
    for sel in selections:
        action_id = sel.get("action_id")
        # Negative IDs are the free walk/run clips bundled with the rig.
        if action_id is None or int(action_id) < 0:
            continue
        runnable.append(sel)
    limit = max(1, int(settings.meshy.max_concurrent_jobs))
    sem = asyncio.Semaphore(limit)

    async def _one(sel: dict) -> StageResult | dict:
        async with sem:
            action_id = int(sel["action_id"])
            action_name = str(sel.get("action_name") or f"idle_{action_id}")
            existing = _reusable_animation_job(previous, rig_task_id, action_id)
            if existing:
                task_id = existing["task_id"]
                writer.log(
                    "info", "Reusing existing animation job", task_id=task_id, action_id=action_id
                )
                result = await resolve_meshy_job(
                    client,
                    task_id,
                    "animation",
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
                    task_type="animation",
                    metadata={
                        "action_id": action_id,
                        "action_name": action_name,
                        "rig_task_id": rig_task_id,
                    },
                    create=lambda aid=action_id: client.animate(
                        rig_task_id, aid, fps=settings.meshy.animation_fps
                    ),
                )
                task_id = result["task_id"]
            if result.get("status") != "SUCCEEDED":
                return StageResult(
                    success=False,
                    stage=StageId.MESHY_ANIMATE.value,
                    error=f"Animation '{action_name}' {describe_task_failure(result)}",
                    data={"task_id": task_id, "action_id": action_id},
                )
            writer.log(
                "info",
                "Idle animation complete",
                task_id=task_id,
                action_name=action_name,
            )
            return {"task_id": task_id, "action_name": action_name}

    try:
        outcomes = await asyncio.gather(*(_one(sel) for sel in runnable))
        for outcome in outcomes:
            if isinstance(outcome, StageResult):
                return outcome
            anim_tasks.append(outcome["task_id"])
            anim_clips.append(outcome)
        pipe.metadata["animation_task_ids"] = anim_tasks
        pipe.metadata["animation_clips"] = anim_clips
        db.update_pipeline_stage(
            ctx.pipeline_id, StageId.MESHY_ANIMATE.value, metadata=pipe.metadata
        )
        names = ", ".join(c["action_name"] for c in anim_clips)
        return StageResult(
            success=True,
            stage=StageId.MESHY_ANIMATE.value,
            message=f"Applied {len(anim_tasks)} idle animations ({names})",
            next_stage=StageId.MESHY_DOWNLOAD.value,
            data={"animation_task_ids": anim_tasks, "animation_clips": anim_clips},
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
        StageId.MESHY_ANIMATE.value,
        _run,
        dry_run=dry_run,
        verbose=verbose,
        force_new=force_new,
    )


if __name__ == "__main__":
    args = stage_argparser("Meshy apply animations").parse_args()
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
