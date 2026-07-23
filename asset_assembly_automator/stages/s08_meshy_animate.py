from __future__ import annotations

import asyncio

from asset_assembly_automator.clients.animation_catalog import AnimationCatalog
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import get_meshy_client, run_stage, stage_argparser


def _idle_query_names(settings) -> list[str]:
    names = [str(n).strip() for n in settings.meshy.default_custom_animations if str(n).strip()]
    return names or ["idle3", "idle4", "idle12"]


def _resolve_idle_selections(settings) -> list[dict]:
    catalog = AnimationCatalog()
    configured = _idle_query_names(settings)
    selections: list[dict] = []
    for query in configured:
        matches = catalog.search(query, limit=5)
        picked = next(
            (m for m in matches if query.lower() in (m.get("action_name") or "").lower()),
            matches[0] if matches else None,
        )
        if picked and picked.get("action_id", 0) > 0:
            selections.append(
                {
                    "action_id": picked["action_id"],
                    "action_name": picked["action_name"],
                }
            )
    if selections:
        return selections
    return catalog.resolve_standard_idles()


async def _run(ctx, db, dirs, writer):
    settings = get_settings()
    pipe = db.get_pipeline(ctx.pipeline_id)
    rig_task_id = pipe.metadata.get("rig_task_id")
    if not rig_task_id:
        job = db.get_external_job(ctx.pipeline_id, "rigging", active_only=False)
        rig_task_id = job["task_id"] if job else None
    if not rig_task_id:
        return StageResult(success=False, stage=StageId.MESHY_ANIMATE.value, error="No rig task")

    selections = db.get_animation_selections(ctx.pipeline_id)
    if not selections:
        await AnimationCatalog().sync()
        selections = _resolve_idle_selections(settings)
        db.set_animation_selections(
            ctx.pipeline_id, [s for s in selections if s.get("action_id", 0) > 0]
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
    anim_tasks: list[str] = []
    anim_clips: list[dict] = []
    try:
        for sel in selections:
            action_id = sel.get("action_id")
            if not action_id or action_id < 0:
                continue
            action_name = str(sel.get("action_name") or f"idle_{action_id}")
            created = await client.animate(
                rig_task_id, int(action_id), fps=settings.meshy.animation_fps
            )
            task_id = created["task_id"]
            anim_tasks.append(task_id)
            anim_clips.append({"task_id": task_id, "action_name": action_name})
            job_id = db.save_external_job(
                ctx.pipeline_id,
                "meshy",
                task_id,
                "animation",
                metadata={"action_id": action_id, "action_name": action_name},
            )
            result = await client.poll_until_done(
                task_id, "animation", cancel_event=ctx.cancel_event
            )
            db.update_external_job(
                job_id,
                status=result.get("status", "SUCCEEDED"),
                credits_used=3,
            )
            writer.log(
                "info",
                "Idle animation complete",
                task_id=task_id,
                action_name=action_name,
            )
        pipe.metadata["animation_task_ids"] = anim_tasks
        pipe.metadata["animation_clips"] = anim_clips
        db.update_pipeline_stage(
            ctx.pipeline_id, StageId.MESHY_ANIMATE.value, metadata=pipe.metadata
        )
        return StageResult(
            success=True,
            stage=StageId.MESHY_ANIMATE.value,
            message=f"Applied {len(anim_tasks)} idle animations (idle3/idle4/idle12)",
            next_stage=StageId.MESHY_DOWNLOAD.value,
            data={"animation_task_ids": anim_tasks, "animation_clips": anim_clips},
        )
    finally:
        if hasattr(client, "close"):
            await client.close()


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.MESHY_ANIMATE.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    args = stage_argparser("Meshy apply animations").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
