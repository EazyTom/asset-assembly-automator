from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.output_paths import chr_file_prefix, pipeline_output_slug
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import run_stage, stage_argparser


async def _run(ctx, db, dirs, writer):
    pipe = db.get_pipeline(ctx.pipeline_id)
    output_slug = pipeline_output_slug(pipe)
    zip_name = f"{chr_file_prefix(output_slug)}_UnityImport_v01.zip"
    zip_path = dirs["root"] / zip_name

    files_to_zip: list[Path] = []
    for sub in ("Source", "Animations", "Textures", "TPose", "Concept"):
        d = dirs["root"] / sub if sub != "Source" else dirs["source"]
        if d.exists():
            files_to_zip.extend(p for p in d.rglob("*") if p.is_file())

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files_to_zip:
            arc = f.relative_to(dirs["root"])
            zf.write(f, arcname=str(arc))

    prompts = db.conn.execute(
        "SELECT provider, final_text, template_id FROM prompts WHERE pipeline_id = ?",
        (ctx.pipeline_id,),
    ).fetchall()
    jobs = db.conn.execute(
        "SELECT provider, task_id, task_type, status, face_count, credits_used FROM external_jobs WHERE pipeline_id = ?",
        (ctx.pipeline_id,),
    ).fetchall()
    manifest = {
        "pipeline_id": ctx.pipeline_id,
        "asset_name": pipe.asset_name,
        "generated_at": datetime.now(UTC).isoformat(),
        "metadata": pipe.metadata,
        "prompts": [dict(p) for p in prompts],
        "external_jobs": [dict(j) for j in jobs],
        "zip": str(zip_path),
    }
    manifest_path = dirs["root"] / "pipeline_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.write(manifest_path, arcname="pipeline_manifest.json")

    db.add_asset(ctx.pipeline_id, "zip", str(zip_path), metadata={"manifest": str(manifest_path)})
    db.update_pipeline_stage(ctx.pipeline_id, StageId.COMPLETE.value, status="complete")
    return StageResult(
        success=True,
        stage=StageId.PACKAGE_EXPORT.value,
        message=f"Exported {zip_path}",
        next_stage=StageId.COMPLETE.value,
        data={"zip_path": str(zip_path), "manifest_path": str(manifest_path)},
    )


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.PACKAGE_EXPORT.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    args = stage_argparser("Package FBX zip export").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
