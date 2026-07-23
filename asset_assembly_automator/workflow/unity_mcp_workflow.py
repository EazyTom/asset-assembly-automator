"""Compose prompts and run Cursor CLI workflows for Unity MCP import/cleanup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.output_paths import pipeline_output_slug
from asset_assembly_automator.workflow.templates import (
    load_unity_cleanup_template,
)

OnLineCallback = Any


def _render_workflow_template(template: str, **values: str) -> str:
    """Replace `{key}` placeholders without interpreting C# braces in the template."""
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def _character_facts(
    *,
    asset_name: str,
    character_slug: str,
    unity_project_path: str,
    character_dir: Path,
    manifest_path: Path | None = None,
    unity_import_zip: Path | str | None = None,
    clips: list[dict[str, str]] | None = None,
    staged_files: list[str] | None = None,
) -> str:
    clip_lines = (
        "\n".join(f"- {c['name']} ({c['type']}): {c['path']}" for c in (clips or []))
        or "- (see manifest)"
    )
    file_lines = "\n".join(f"- {p}" for p in (staged_files or [])) or "- (see manifest)"
    manifest_line = str(manifest_path) if manifest_path else "(not staged yet)"
    zip_line = (
        str(unity_import_zip) if unity_import_zip else "(no zip — use staged FBXs in character_dir)"
    )
    return f"""
## Facts (auto-generated — do not ignore)

- Asset display name: {asset_name}
- Character slug / Unity folder name: {character_slug}
- Unity project path: {unity_project_path}
- Character directory: {character_dir}
- Unity import zip: {zip_line}
- Manifest: {manifest_line}
- Prefab / scene object name: PF_{character_slug}
- Rig FBX: {character_dir}/Source/Character_output.fbx
- Walk FBX: {character_dir}/Source/Animation_Walking_withSkin.fbx
- Run FBX: {character_dir}/Source/Animation_Running_withSkin.fbx
- Idle FBXs: {character_dir}/Animations/Animation_idle3_withSkin.fbx (and idle4, idle12)
- Textures folder: {character_dir}/Textures (base-color PNG staged here)
- Material out: {character_dir}/Materials/MAT_{character_slug}_Body.mat
- Controller out: {character_dir}/Controllers/{character_slug}_Controller.controller
- Prefab out: {character_dir}/Prefabs/PF_{character_slug}.prefab
- MCP server: user-unity-mcp (not user-unityMCP)
- Helper scripts (AAA installs before MCP; verify in Phase 0):
  - Assets/Editor/CharacterManifestImportUtility.cs
  - Assets/Scripts/CharacterOvalPatrol.cs
- Import trigger: Unity_RunCommand calling CharacterManifestImportUtility.ImportFromSlug("{character_slug}")
  OR menu Tools/Characters/Import character from manifest...
- Do not use Unity_ImportExternalModel or inline SaveAndReimport scripts

### Staged files
{file_lines}

### Animation clips
{clip_lines}
""".strip()


def _cleanup_facts(
    *,
    asset_name: str,
    character_slug: str,
    unity_project_path: str,
    character_dir: Path,
) -> str:
    return f"""
## Facts (auto-generated — do not ignore)

- **Selected character only** — remove slug `{character_slug}` and nothing else
- Asset display name: {asset_name}
- Character slug (from workflow dropdown): {character_slug}
- Unity project path: {unity_project_path}
- Character directory to delete: {character_dir}
- Scene object names to destroy: `PF_{character_slug}` or `{character_slug}` (case-insensitive, active scene)
- Prefab asset path: {character_dir}/Prefabs/PF_{character_slug}.prefab
- Legacy patrol script (delete if present): Assets/Scripts/{character_slug}CircularPatrol.cs
- Agent-created Editor import utilities matching slug (delete if present): Assets/Editor/*{character_slug}*ImportUtility.cs
- Cleanup succeeds only when execute_code returns a line starting with SUCCESS
- Do NOT delete other characters under Assets/Characters/
""".strip()


def compose_cleanup_prompt(
    *,
    asset_name: str,
    character_slug: str,
    unity_project_path: str,
    character_dir: Path,
    guidance: str | None = None,
) -> str:
    template = guidance or load_unity_cleanup_template()
    rendered = _render_workflow_template(
        template,
        character_slug=character_slug,
        unity_project_path=unity_project_path,
        character_dir=str(character_dir),
    )
    facts = _cleanup_facts(
        asset_name=asset_name,
        character_slug=character_slug,
        unity_project_path=unity_project_path,
        character_dir=character_dir,
    )
    return f"{rendered}\n\n{facts}"


def compose_import_prompt(
    guidance: str,
    *,
    asset_name: str,
    character_slug: str,
    unity_project_path: str,
    character_dir: Path,
    manifest_path: Path,
    staged_files: list[str],
    clips: list[dict[str, str]],
    unity_import_zip: Path | str | None = None,
) -> str:
    rendered = _render_workflow_template(
        guidance,
        character_slug=character_slug,
        unity_project_path=unity_project_path,
        character_dir=str(character_dir),
        unity_import_zip=str(unity_import_zip or ""),
        manifest_path=str(manifest_path),
        clips=json.dumps(clips, indent=2),
    )
    facts = _character_facts(
        asset_name=asset_name,
        character_slug=character_slug,
        unity_project_path=unity_project_path,
        character_dir=character_dir,
        manifest_path=manifest_path,
        unity_import_zip=unity_import_zip,
        staged_files=staged_files,
        clips=clips,
    )
    return f"{rendered}\n\n{facts}"


def unity_character_dir(db: Database, pipeline_id: int) -> tuple[Path, str, str]:
    pipe = db.get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError(f"Pipeline {pipeline_id} not found")
    project = db.get_project(pipe.project_id)
    if not project or not project.unity_project_path:
        raise ValueError("Unity project path is not set on this project")
    slug = pipeline_output_slug(pipe)
    character_dir = Path(project.unity_project_path) / "Assets" / "Characters" / slug
    return character_dir, slug, pipe.asset_name


def _cursor_prompt_dir(character_dir: Path) -> Path:
    return character_dir / ".aaa"


async def run_unity_import_workflow(
    *,
    prompt: str,
    unity_project_path: str | Path,
    character_dir: Path,
    character_slug: str,
    dry_run: bool = False,
    on_line: OnLineCallback | None = None,
) -> dict[str, Any]:
    """Run Unity MCP import via Cursor CLI with the prompt attached as a markdown file."""
    from asset_assembly_automator.stages._base import get_cursor_cli_client

    client = get_cursor_cli_client(dry_run)
    health = await client.health_check()
    if not health.get("available"):
        return {
            "success": False,
            "reason": health.get("reason") or "Cursor CLI unavailable",
        }

    if on_line:
        prompt_path = _cursor_prompt_dir(character_dir) / f"unity_import_{character_slug}.md"
        await on_line(
            "info",
            f"Unity import prompt will attach: {prompt_path.name}",
            {
                "provider": "unity_import",
                "character_slug": character_slug,
                "character_dir": str(character_dir),
                "unity_project_path": str(unity_project_path),
                "prompt_file": str(prompt_path),
            },
        )
        await on_line(
            "info",
            "Launching Cursor CLI agent with Unity MCP import workflow (.md attachment)",
            {"provider": "cursor_cli"},
        )

    settings = get_settings().cursor_cli
    return await client.run_workflow(
        prompt,
        cwd=unity_project_path,
        model=settings.model or None,
        timeout=settings.timeout_seconds,
        on_line=on_line,
        prompt_file_name=f"unity_import_{character_slug}",
        prompt_dir=_cursor_prompt_dir(character_dir),
    )


async def run_unity_cleanup_workflow(
    db: Database,
    pipeline_id: int,
    *,
    dry_run: bool = False,
    guidance: str | None = None,
    on_line: OnLineCallback | None = None,
) -> dict[str, Any]:
    character_dir, slug, asset_name = unity_character_dir(db, pipeline_id)
    project = db.get_project(db.get_pipeline(pipeline_id).project_id)  # type: ignore[union-attr]
    prompt = compose_cleanup_prompt(
        asset_name=asset_name,
        character_slug=slug,
        unity_project_path=str(project.unity_project_path),
        character_dir=character_dir,
        guidance=guidance,
    )
    from asset_assembly_automator.stages._base import get_cursor_cli_client

    client = get_cursor_cli_client(dry_run)
    health = await client.health_check()
    if not health.get("available"):
        return {
            "success": False,
            "reason": health.get("reason") or "Cursor CLI unavailable",
        }

    if on_line:
        await on_line(
            "info",
            (
                f"Unity cleanup targets: PF_{slug}, Assets/Characters/{slug}/, "
                f"Assets/Scripts/{slug}CircularPatrol.cs"
            ),
            {
                "provider": "unity_cleanup",
                "character_slug": slug,
                "character_dir": str(character_dir),
                "unity_project_path": str(project.unity_project_path),
            },
        )
        await on_line(
            "info",
            "Launching Cursor CLI agent with Unity cleanup workflow (.md attachment)",
            {"provider": "cursor_cli"},
        )

    settings = get_settings().cursor_cli
    result = await client.run_workflow(
        prompt,
        cwd=project.unity_project_path,
        model=settings.model or None,
        timeout=settings.timeout_seconds,
        on_line=on_line,
        prompt_file_name=f"unity_cleanup_{slug}",
        prompt_dir=_cursor_prompt_dir(character_dir),
    )
    return result
