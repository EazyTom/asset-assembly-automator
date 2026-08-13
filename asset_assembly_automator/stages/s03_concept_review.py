from __future__ import annotations

import asyncio

from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.output_paths import pipeline_output_slug, tpose_approved_path
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import run_stage, stage_argparser


async def _run(ctx, db, dirs, writer):
    assets = db.get_assets(ctx.pipeline_id, "concept")
    if not assets:
        return StageResult(
            success=False,
            stage=StageId.CONCEPT_REVIEW.value,
            error="No concept assets to review",
        )
    selected_id = ctx.extra.get("selected_asset_id") or assets[0]["id"]
    provider = ctx.extra.get("provider") or assets[0].get("provider", "higgsfield")
    db.conn.execute(
        "UPDATE pipelines SET selected_concept_asset_id = ?, selected_concept_provider = ? WHERE id = ?",
        (selected_id, provider, ctx.pipeline_id),
    )
    db.conn.commit()
    asset = next(a for a in assets if a["id"] == selected_id)
    from asset_assembly_automator.clients.concept_images import is_valid_image

    if not is_valid_image(asset["file_path"]):
        return StageResult(
            success=False,
            stage=StageId.CONCEPT_REVIEW.value,
            error=f"Concept image is invalid or corrupt: {asset['file_path']}",
        )
    pipe = db.get_pipeline(ctx.pipeline_id)
    output_slug = pipeline_output_slug(pipe)
    approved = tpose_approved_path(dirs, output_slug)
    approved.parent.mkdir(parents=True, exist_ok=True)
    from shutil import copy2

    copy2(asset["file_path"], approved)
    db.add_asset(ctx.pipeline_id, "tpose", str(approved), provider=provider)
    next_stage = StageId.MAGNIFIC_UPREZ.value
    return StageResult(
        success=True,
        stage=StageId.CONCEPT_REVIEW.value,
        message=f"Approved concept {selected_id}",
        next_stage=next_stage,
        data={"approved_path": str(approved)},
    )


async def run(
    pipeline_id: int,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    selected_asset_id: int | None = None,
    provider: str | None = None,
    **kwargs,
):
    async def _wrapped(ctx, db, dirs, writer):
        ctx.extra["selected_asset_id"] = selected_asset_id
        ctx.extra["provider"] = provider
        return await _run(ctx, db, dirs, writer)

    return await run_stage(
        pipeline_id, StageId.CONCEPT_REVIEW.value, _wrapped, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    p = stage_argparser("Approve concept for pipeline")
    p.add_argument("--selected-asset-id", type=int)
    p.add_argument("--provider")
    args = p.parse_args()
    print(
        asyncio.run(
            run(
                args.pipeline_id,
                dry_run=args.dry_run,
                verbose=args.verbose,
                selected_asset_id=args.selected_asset_id,
                provider=args.provider,
            )
        )
    )
