from __future__ import annotations

import asyncio
from pathlib import Path

from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import (
    get_higgsfield_client,
    load_template,
    run_stage,
    stage_argparser,
)


async def _run(ctx, db, dirs, writer):
    pipe = db.get_pipeline(ctx.pipeline_id)
    tpose_assets = db.get_assets(ctx.pipeline_id, "tpose")
    if not tpose_assets:
        return StageResult(success=False, stage=StageId.TURNAROUND.value, error="No T-pose image")
    front_path = tpose_assets[0]["file_path"]
    tmpl = load_template("higgsfield_character.yaml")
    prompt = tmpl.get("turnaround_template", "{identity} turnaround").format(
        identity=pipe.asset_name
    )
    settings = get_settings()
    client = get_higgsfield_client(ctx.dry_run, dirs["concept"])
    views_dir = dirs["concept"] / "turnaround"
    views_dir.mkdir(parents=True, exist_ok=True)
    result = await client.generate_image(
        prompt, model=settings.higgsfield.turnaround_model, count=4
    )
    paths = [front_path]
    for i, item in enumerate(result.get("results", [])):
        p = item.get("local_path") or str(views_dir / f"view_{i}.png")
        if not Path(p).exists() and ctx.dry_run:
            Path(p).write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(p)
        db.add_asset(ctx.pipeline_id, "concept", p, provider="higgsfield", metadata={"view": i})
    pipe.metadata["turnaround_paths"] = paths
    db.update_pipeline_stage(ctx.pipeline_id, StageId.TURNAROUND.value, metadata=pipe.metadata)
    return StageResult(
        success=True,
        stage=StageId.TURNAROUND.value,
        message=f"Generated {len(paths)} turnaround views",
        next_stage=StageId.MESHY_I2D.value,
        data={"paths": paths},
    )


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.TURNAROUND.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    args = stage_argparser("Generate multi-view turnaround").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
