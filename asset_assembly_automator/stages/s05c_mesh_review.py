"""Manual gate: approve the original image-to-3D mesh or a retextured variant."""

from __future__ import annotations

import asyncio

from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.output_paths import pipeline_character_slug, preview_png_path
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import run_stage, stage_argparser

REVIEWABLE_TASK_TYPES = ["image-to-3d", "retexture"]


def mesh_variants(db, pipeline_id: int) -> list[dict]:
    """Succeeded meshes the user can approve, oldest first."""
    return [
        j
        for j in db.list_external_jobs(pipeline_id, REVIEWABLE_TASK_TYPES)
        if j.get("status") == "SUCCEEDED"
    ]


async def _run(ctx, db, dirs, writer):
    stage = StageId.MESH_REVIEW.value
    pipe = db.get_pipeline(ctx.pipeline_id)
    variants = mesh_variants(db, ctx.pipeline_id)
    if not variants:
        return StageResult(success=False, stage=stage, error="No finished mesh to approve")

    wanted = ctx.extra.get("task_id")
    if wanted:
        chosen = next((v for v in variants if v["task_id"] == wanted), None)
        if not chosen:
            return StageResult(
                success=False,
                stage=stage,
                error=f"Task {wanted} is not a finished mesh or variant of this pipeline",
            )
    else:
        chosen = next(v for v in reversed(variants) if v["task_type"] == "image-to-3d")

    pipe.metadata["mesh_source"] = {
        "task_id": chosen["task_id"],
        "task_type": chosen["task_type"],
    }
    thumb = (chosen.get("metadata") or {}).get("thumbnail_path")
    if chosen["task_type"] == "image-to-3d":
        original = preview_png_path(dirs, pipeline_character_slug(pipe))
        if original.is_file():
            pipe.metadata["mesh_preview_path"] = str(original)
    elif thumb:
        pipe.metadata["mesh_preview_path"] = thumb
    db.update_pipeline_stage(ctx.pipeline_id, stage, metadata=pipe.metadata)
    writer.log(
        "info",
        "Mesh approved",
        task_id=chosen["task_id"],
        task_type=chosen["task_type"],
        prompt=(chosen.get("metadata") or {}).get("prompt"),
    )
    label = "original mesh" if chosen["task_type"] == "image-to-3d" else "retextured variant"
    return StageResult(
        success=True,
        stage=stage,
        message=f"Approved {label} {chosen['task_id']}",
        next_stage=StageId.MESHY_REMESH.value,
        data={"task_id": chosen["task_id"], "task_type": chosen["task_type"]},
    )


async def run(
    pipeline_id: int,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    task_id: str | None = None,
    **kwargs,
):
    return await run_stage(
        pipeline_id,
        StageId.MESH_REVIEW.value,
        _run,
        dry_run=dry_run,
        verbose=verbose,
        task_id=task_id,
    )


if __name__ == "__main__":
    parser = stage_argparser("Approve mesh variant")
    parser.add_argument("--task-id", default=None)
    args = parser.parse_args()
    print(
        asyncio.run(
            run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose, task_id=args.task_id)
        )
    )
