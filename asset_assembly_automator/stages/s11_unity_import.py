from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from asset_assembly_automator.clients.agent_cli import get_agent_cli
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.output_paths import pipeline_output_slug
from asset_assembly_automator.core.state_machine import StageId, asset_kind_for_pipeline
from asset_assembly_automator.stages._base import run_stage, stage_argparser
from asset_assembly_automator.workflow.templates import load_unity_import_repair_template
from asset_assembly_automator.workflow.unity_helpers import (
    ensure_unity_import_package,
    unity_asset_root,
)
from asset_assembly_automator.workflow.unity_import_poll import (
    import_result_path,
    poll_import_result,
    write_import_request,
)
from asset_assembly_automator.workflow.unity_mcp_bridges import (
    compose_bridge_facts,
    resolve_unity_mcp_bridge,
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
            if clip:
                clips.append(clip)
    for path in sorted(anim_dir.glob("*.fbx")):
        clip = _classify(path)
        if clip and not any(c["path"] == clip["path"] for c in clips):
            clips.append(clip)
    return clips


def _build_manifest(
    *,
    pipe,
    ctx,
    unity_root: Path,
    asset_dir: Path,
    output_slug: str,
    asset_kind: str,
    clips: list[dict[str, str]],
    staged_files: list[str],
    zip_path: str | None,
    helper_summary: str,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "pipeline_id": ctx.pipeline_id,
        "asset_name": pipe.asset_name,
        "asset_kind": asset_kind,
        "unity_project_path": str(unity_root),
        "character_dir": str(asset_dir),
        "unity_import_zip": zip_path,
        "clips": clips,
        "staged_files": staged_files,
        "texture_resolution": pipe.metadata.get("texture_resolution", "8k"),
        "aaa_helpers": {
            "installed_by": "s11_unity_import",
            "helper_summary": helper_summary,
            "package": "com.assetassembly.import",
        },
    }
    if asset_kind == "character":
        manifest["rig_config"] = {
            "animationType": "Human",
            "avatarSetup": "CreateFromThisModel",
            "globalScale": 0.01,
        }
        manifest["animator"] = {
            "controller": f"Controllers/{output_slug}_Controller.controller",
            "idle_clips": ["Idle3", "Idle4", "Idle12"],
            "locomotion_clips": ["Walk", "Run"],
            "default_state": "Idle3",
        }
        manifest["scene"] = {
            "prefab_name": f"PF_{output_slug}",
            "terrain_detection": "Terrain.activeTerrain or FindObjectOfType<Terrain>()",
            "patrol": "idle cycle with occasional oval walk",
            "default_animator_gait": 0,
            "default_idle_index": 0,
            "no_scripts": False,
        }
    else:
        manifest["scene"] = {
            "prefab_name": f"PF_{output_slug}",
            "controller": "DriveController" if asset_kind == "vehicle" else "FlightController",
        }
    return manifest


async def _run_repair(
    *,
    ctx,
    db,
    writer,
    unity_root: Path,
    asset_dir: Path,
    output_slug: str,
    asset_kind: str,
    validation: dict[str, Any],
) -> dict[str, Any]:
    template = load_unity_import_repair_template()
    bridge = resolve_unity_mcp_bridge(db=db)
    prompt = template.format(
        slug=output_slug,
        asset_kind=asset_kind,
        unity_project_path=str(unity_root),
        asset_dir=str(asset_dir),
        validation_json=json.dumps(validation, indent=2),
        mcp_server=bridge.mcp_config_key,
        cursor_server_id=bridge.cursor_server_id,
        execute_code_tool=bridge.execute_code_tool,
        console_tool=bridge.console_tool,
        ping_tool=bridge.ping_tool,
    )
    prompt = f"{prompt}\n\n{compose_bridge_facts(db=db)}"
    client = get_agent_cli(dry_run=ctx.dry_run, db=db)
    health = await client.health_check()
    if not health.get("available"):
        writer.log("error", f"Agent CLI unavailable: {health.get('reason')}")
        return {"success": False, "reason": health.get("reason")}

    repo_root = Path(__file__).resolve().parents[2]
    mcp_config = str(repo_root / ".mcp.json")

    async def _on_line(level: str, message: str, context: dict[str, Any]) -> None:
        writer.log(level, message, **context)

    writer.log(
        "info", "Starting agent repair workflow", provider=getattr(client, "provider_name", "agent")
    )
    return await client.run_workflow(
        prompt,
        cwd=str(unity_root),
        on_line=_on_line,
        prompt_file_name=f"unity_repair_{output_slug}",
        mcp_config=mcp_config if hasattr(client, "provider_name") else None,
    )


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
            error="Unity project path is not set on this project.",
        )

    unity_root = Path(project.unity_project_path)
    asset_kind = asset_kind_for_pipeline(pipe)
    output_slug = pipeline_output_slug(pipe)

    try:
        helper_result = ensure_unity_import_package(unity_root)
    except OSError as exc:
        return StageResult(
            success=False,
            stage=StageId.UNITY_IMPORT.value,
            error=f"Could not install Unity import package: {exc}",
        )
    if helper_result.missing_source:
        return StageResult(
            success=False,
            stage=StageId.UNITY_IMPORT.value,
            error="Unity import package missing from AAA install (unity_package/com.assetassembly.import)",
        )

    asset_dir = unity_asset_root(unity_root, asset_kind, output_slug)
    for sub in ("Source", "Textures", "Animations", "Materials", "Prefabs", "Controllers", ".aaa"):
        (asset_dir / sub).mkdir(parents=True, exist_ok=True)

    staged_files: list[str] = []

    def _copy_tree(src: Path, dest: Path) -> None:
        if not src.exists():
            return
        for item in src.iterdir():
            if item.is_file():
                target = dest / item.name
                shutil.copy2(item, target)
                staged_files.append(str(target))

    _copy_tree(dirs["source"], asset_dir / "Source")
    if asset_kind == "character":
        _copy_tree(dirs["animations"], asset_dir / "Animations")
    tex_src = dirs["source"] / "Textures"
    if tex_src.exists():
        _copy_tree(tex_src, asset_dir / "Textures")
    elif dirs["textures"].exists():
        _copy_tree(dirs["textures"], asset_dir / "Textures")

    clips = (
        _collect_clips(asset_dir / "Source", asset_dir / "Animations", pipe.asset_name)
        if asset_kind == "character"
        else []
    )

    zip_path: str | None = None
    meta_zip = pipe.metadata.get("meshy_export_zip")
    if isinstance(meta_zip, str) and meta_zip.strip() and Path(meta_zip).is_file():
        zip_path = meta_zip.strip()

    manifest = _build_manifest(
        pipe=pipe,
        ctx=ctx,
        unity_root=unity_root,
        asset_dir=asset_dir,
        output_slug=output_slug,
        asset_kind=asset_kind,
        clips=clips,
        staged_files=staged_files,
        zip_path=zip_path,
        helper_summary=helper_result.summary(),
    )
    manifest_path = asset_dir / "unity_import_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    staged_files.append(str(manifest_path))

    writer.log("info", "Unity package ready", helpers=helper_result.summary())

    if ctx.dry_run:
        result_payload = {"ok": True, "duration_ms": 0, "checks": ["dry_run"], "errors": []}
        result_path = import_result_path(asset_dir)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result_payload), encoding="utf-8")
    else:
        write_import_request(
            asset_dir,
            slug=output_slug,
            asset_kind=asset_kind,
            texture_resolution=str(pipe.metadata.get("texture_resolution", "8k")),
        )
        writer.log("info", "Waiting for Unity Editor import (C# watcher)")
        result_payload = await poll_import_result(
            import_result_path(asset_dir),
            timeout_seconds=300.0,
            cancel_event=ctx.cancel_event,
        )

    if not result_payload.get("ok"):
        writer.log(
            "warning",
            "Deterministic import failed — attempting agent repair",
            errors=result_payload.get("errors"),
        )
        repair = await _run_repair(
            ctx=ctx,
            db=db,
            writer=writer,
            unity_root=unity_root,
            asset_dir=asset_dir,
            output_slug=output_slug,
            asset_kind=asset_kind,
            validation=result_payload,
        )
        if repair.get("success") and not ctx.dry_run:
            write_import_request(
                asset_dir,
                slug=output_slug,
                asset_kind=asset_kind,
                texture_resolution=str(pipe.metadata.get("texture_resolution", "8k")),
            )
            result_payload = await poll_import_result(
                import_result_path(asset_dir),
                timeout_seconds=180.0,
                cancel_event=ctx.cancel_event,
            )

    meta = {
        **pipe.metadata,
        "unity_import_path": str(asset_dir),
        "unity_import_manifest": str(manifest_path),
        "unity_import_result": result_payload,
    }
    db.add_asset(
        ctx.pipeline_id,
        "unity_import",
        str(asset_dir),
        provider="unity",
        metadata={"manifest": str(manifest_path), "result": result_payload},
    )
    db.update_pipeline_stage(ctx.pipeline_id, StageId.UNITY_IMPORT.value, metadata=meta)

    if not result_payload.get("ok"):
        errors = result_payload.get("errors") or ["Unity import validation failed"]
        return StageResult(
            success=False,
            stage=StageId.UNITY_IMPORT.value,
            error="; ".join(str(e) for e in errors),
            message="Unity import failed",
            data=result_payload,
        )

    return StageResult(
        success=True,
        stage=StageId.UNITY_IMPORT.value,
        message=f"Unity import completed: {asset_dir}",
        data=result_payload,
    )


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.UNITY_IMPORT.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    import asyncio

    args = stage_argparser("Unity import via C# package + optional agent repair").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
