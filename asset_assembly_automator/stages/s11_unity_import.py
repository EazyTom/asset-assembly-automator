from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.output_paths import chr_file_prefix, pipeline_output_slug
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import run_stage, stage_argparser
from asset_assembly_automator.workflow.templates import load_unity_import_template
from asset_assembly_automator.workflow.unity_helpers import ensure_unity_import_helpers
from asset_assembly_automator.workflow.unity_mcp_workflow import (
    compose_import_prompt,
    run_unity_import_workflow,
)


def _collect_clips(source_dir: Path, anim_dir: Path, asset_name: str) -> list[dict[str, str]]:
    clips: list[dict[str, str]] = []
    idle_hints = (("idle12", "Idle12"), ("idle4", "Idle4"), ("idle3", "Idle3"))

    def _classify(path: Path) -> dict[str, str] | None:
        name_lower = path.name.lower()
        if "walking" in name_lower or ("walk" in name_lower and "idle" not in name_lower):
            return {"name": "Walk", "path": str(path), "type": "locomotion"}
        if "running" in name_lower or ("run" in name_lower and "idle" not in name_lower):
            return {"name": "Run", "path": str(path), "type": "locomotion"}
        if "character_output" in name_lower or path.name.endswith("_rig.fbx"):
            return {"name": "RigMesh", "path": str(path), "type": "rig"}
        for hint, role in idle_hints:
            if hint in name_lower:
                return {"name": role, "path": str(path), "type": "idle"}
        return {"name": path.stem, "path": str(path), "type": "custom"}

    if source_dir.exists():
        for path in sorted(source_dir.glob("*.fbx")):
            clip = _classify(path)
            if clip and clip["type"] != "custom":
                clips.append(clip)
            elif clip:
                clips.append(clip)
    legacy_patterns = (
        (f"CHR_{asset_name}_rig_walking.fbx", "Walk"),
        (f"CHR_{asset_name}_rig_running.fbx", "Run"),
        (f"CHR_{asset_name}_rig.fbx", "RigMesh"),
    )
    for pattern, role in legacy_patterns:
        path = source_dir / pattern
        if path.exists() and not any(c["path"] == str(path) for c in clips):
            clip_type = "rig" if role == "RigMesh" else "locomotion"
            clips.append({"name": role, "path": str(path), "type": clip_type})
    for path in sorted(anim_dir.glob("*.fbx")):
        clip = _classify(path)
        if clip and not any(c["path"] == clip["path"] for c in clips):
            clips.append(clip)
    return clips


async def _run(ctx, db, dirs, writer):
    pipe = db.get_pipeline(ctx.pipeline_id)
    if not pipe:
        return StageResult(
            success=False, stage=StageId.UNITY_IMPORT.value, error="Pipeline not found"
        )

    project = db.get_project(pipe.project_id)
    if not project or not project.unity_project_path:
        return StageResult(
            success=False,
            stage=StageId.UNITY_IMPORT.value,
            error="Unity project path is not set on this project. Configure it in the workflow app.",
        )

    unity_root = Path(project.unity_project_path)

    try:
        helper_result = ensure_unity_import_helpers(unity_root)
    except OSError as exc:
        return StageResult(
            success=False,
            stage=StageId.UNITY_IMPORT.value,
            error=f"Could not install Unity helper scripts: {exc}",
        )
    if helper_result.missing_templates:
        return StageResult(
            success=False,
            stage=StageId.UNITY_IMPORT.value,
            error="Unity helper templates missing from AAA install: "
            + ", ".join(helper_result.missing_templates),
        )

    output_slug = pipeline_output_slug(pipe)
    character_dir = unity_root / "Assets" / "Characters" / output_slug
    for sub in ("Source", "Textures", "Animations", "Materials", "Prefabs", "Controllers"):
        (character_dir / sub).mkdir(parents=True, exist_ok=True)

    staged_files: list[str] = []

    def _copy_tree(src: Path, dest: Path) -> None:
        if not src.exists():
            return
        for item in src.iterdir():
            if item.is_file():
                target = dest / item.name
                shutil.copy2(item, target)
                staged_files.append(str(target))

    _copy_tree(dirs["source"], character_dir / "Source")
    _copy_tree(dirs["animations"], character_dir / "Animations")
    tex_src = dirs["source"] / "Textures"
    if tex_src.exists():
        _copy_tree(tex_src, character_dir / "Textures")
    elif dirs["textures"].exists():
        _copy_tree(dirs["textures"], character_dir / "Textures")

    clips = _collect_clips(character_dir / "Source", character_dir / "Animations", pipe.asset_name)

    zip_path: str | None = None
    meta_zip = pipe.metadata.get("meshy_export_zip")
    if isinstance(meta_zip, str) and meta_zip.strip() and Path(meta_zip).is_file():
        zip_path = meta_zip.strip()
    else:
        for row in db.get_assets(ctx.pipeline_id, "zip"):
            candidate = row.get("file_path")
            if candidate and Path(str(candidate)).is_file():
                zip_path = str(candidate)
                break
    if not zip_path:
        candidate = dirs["root"] / f"{chr_file_prefix(output_slug)}_UnityImport_v01.zip"
        if candidate.is_file():
            zip_path = str(candidate)

    manifest = {
        "pipeline_id": ctx.pipeline_id,
        "asset_name": pipe.asset_name,
        "unity_project_path": str(unity_root),
        "character_dir": str(character_dir),
        "unity_import_zip": zip_path,
        "clips": clips,
        "staged_files": staged_files,
        "rig_config": {
            "animationType": "Human",
            "avatarSetup": "CreateFromThisModel",
            "globalScale": 0.01,
        },
        "animator": {
            "controller": f"Controllers/{output_slug}_Controller.controller",
            "idle_clips": ["Idle3", "Idle4", "Idle12"],
            "locomotion_clips": ["Walk", "Run"],
            "default_state": "Idle3",
        },
        "scene": {
            "prefab_name": f"PF_{output_slug}",
            "terrain_detection": "Terrain.activeTerrain or FindObjectOfType<Terrain>()",
            "patrol": "idle cycle with occasional oval walk",
            "default_animator_gait": 0,
            "default_idle_index": 0,
            "no_scripts": False,
        },
        "aaa_helpers": {
            "installed_by": "s11_unity_import",
            "helper_summary": helper_result.summary(),
            "editor_script": "Assets/Editor/CharacterManifestImportUtility.cs",
            "runtime_script": "Assets/Scripts/CharacterOvalPatrol.cs",
        },
    }
    manifest_path = character_dir / "unity_import_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    staged_files.append(str(manifest_path))

    writer.log("info", "Unity helper scripts ready", helpers=helper_result.summary())

    guidance = pipe.metadata.get("unity_import_instructions") or load_unity_import_template()
    prompt = compose_import_prompt(
        guidance,
        asset_name=pipe.asset_name,
        character_slug=output_slug,
        unity_project_path=str(unity_root),
        character_dir=character_dir,
        manifest_path=manifest_path,
        staged_files=staged_files,
        clips=clips,
        unity_import_zip=zip_path,
    )

    from asset_assembly_automator.stages._base import get_cursor_cli_client

    client = get_cursor_cli_client(ctx.dry_run)
    health = await client.health_check()
    if not health.get("available"):
        writer.log(
            "error",
            f"Cursor CLI unavailable: {health.get('reason')}",
            provider="cursor_cli",
        )
        return StageResult(
            success=False,
            stage=StageId.UNITY_IMPORT.value,
            error=str(health.get("reason") or "Cursor CLI unavailable"),
            message="Files staged; Cursor CLI not available for Unity MCP import",
            data={"character_dir": str(character_dir), "manifest_path": str(manifest_path)},
        )

    writer.log("info", "Starting Cursor CLI Unity import workflow", provider="cursor_cli")

    async def _on_line(level: str, message: str, context: dict[str, Any]) -> None:
        writer.log(level, message, **context)

    result = await run_unity_import_workflow(
        prompt=prompt,
        unity_project_path=unity_root,
        character_dir=character_dir,
        character_slug=output_slug,
        dry_run=ctx.dry_run,
        on_line=_on_line,
    )

    meta = {
        **pipe.metadata,
        "unity_import_path": str(character_dir),
        "unity_import_manifest": str(manifest_path),
        "unity_import_prompt_file": result.get("prompt_file"),
        "unity_import_result": {
            "success": result.get("success"),
            "returncode": result.get("returncode"),
            "final_text": result.get("final_text"),
            "prompt_file": result.get("prompt_file"),
        },
    }
    db.add_asset(
        ctx.pipeline_id,
        "unity_import",
        str(character_dir),
        provider="unity",
        metadata={"manifest": str(manifest_path)},
    )
    db.update_pipeline_stage(ctx.pipeline_id, StageId.UNITY_IMPORT.value, metadata=meta)

    if not result.get("success"):
        return StageResult(
            success=False,
            stage=StageId.UNITY_IMPORT.value,
            error=result.get("final_text") or f"Cursor CLI exit {result.get('returncode')}",
            message="Unity import workflow failed",
            data=meta["unity_import_result"],
        )

    return StageResult(
        success=True,
        stage=StageId.UNITY_IMPORT.value,
        message=f"Unity import workflow completed: {character_dir}",
        data=meta["unity_import_result"],
    )


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.UNITY_IMPORT.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    import asyncio

    args = stage_argparser("Unity import via Cursor CLI + MCP").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
