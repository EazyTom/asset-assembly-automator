from __future__ import annotations

import asyncio
from pathlib import Path

from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import run_stage, stage_argparser


async def _run(ctx, db, dirs, writer):
    pipe = db.get_pipeline(ctx.pipeline_id)
    issues: list[str] = []

    fbx_assets = db.get_assets(ctx.pipeline_id, "fbx")
    if not fbx_assets:
        issues.append("No FBX assets recorded")

    source_fbx = sorted(dirs["source"].glob("*.fbx")) if dirs["source"].exists() else []
    if not source_fbx:
        issues.append("No rig FBX found in Source/")

    tex_dir = dirs["textures"]
    texture_files = list(tex_dir.glob("*.png")) if tex_dir.exists() else []
    if not texture_files:
        src_tex = dirs["source"] / "Textures"
        if src_tex.exists() and any(src_tex.glob("*.png")):
            tex_dir.mkdir(parents=True, exist_ok=True)
            for f in src_tex.glob("*.png"):
                (tex_dir / f.name).write_bytes(f.read_bytes())
            texture_files = list(tex_dir.glob("*.png"))
    if not texture_files:
        issues.append("No textures found")

    meshy_zip = pipe.metadata.get("meshy_export_zip")
    if meshy_zip and not Path(meshy_zip).exists():
        issues.append("Meshy export zip missing on disk")

    face_count = pipe.metadata.get("face_count")
    if face_count and face_count > 300000:
        issues.append(f"Face count {face_count} exceeds hard rig limit")

    manifest_fields = ["i2d_task_id", "rig_task_id"]
    for field in manifest_fields:
        if not pipe.metadata.get(field):
            issues.append(f"Missing manifest field: {field}")

    passed = len(issues) == 0
    writer.log("info" if passed else "warning", "QC gate", issues=issues, passed=passed)
    return StageResult(
        success=passed,
        stage=StageId.MESHY_QC.value,
        message="QC passed" if passed else f"QC failed: {issues}",
        next_stage=StageId.PACKAGE_EXPORT.value if passed else None,
        data={"issues": issues},
        error=None if passed else "; ".join(issues),
    )


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.MESHY_QC.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    args = stage_argparser("QC validate pipeline outputs").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
