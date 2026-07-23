"""Local maintenance helpers for workflow GUI (reset DB, delete output folders)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from asset_assembly_automator.core.db.models import (
    Database,
    Pipeline,
    Project,
    reset_local_database,
)
from asset_assembly_automator.core.output_paths import (
    character_output_root,
    ensure_pipeline_output_slug,
    folder_output_slug,
    project_output_slug,
)


def validate_output_delete_path(path: Path) -> str | None:
    """Return an error message when deleting ``path`` would be unsafe."""
    text = str(path)
    if "<character_slug>" in text:
        return "Select a character or enter a character name before deleting the output folder."
    resolved = path.resolve()
    if not resolved.exists():
        return f"Folder does not exist:\n{resolved}"
    if not resolved.is_dir():
        return f"Not a directory:\n{resolved}"

    blocked_names = {"output", "characters", "assetassemblyautomator"}
    if resolved.name.lower() in blocked_names:
        return f"Refusing to delete a top-level folder:\n{resolved}"

    parent_name = resolved.parent.name.lower()
    if parent_name == "characters":
        return None
    if parent_name in blocked_names and "-" not in resolved.name:
        return (
            "Refusing to delete the project output root. "
            "Select a character to delete its folder only."
        )
    return None


def delete_output_directory(path: Path) -> Path:
    """Delete a character/project output directory after validation."""
    error = validate_output_delete_path(path)
    if error:
        raise ValueError(error)
    resolved = path.resolve()
    shutil.rmtree(resolved)
    return resolved


def reset_application_database(db: Database | None = None) -> tuple[Path, Database]:
    """Reset the on-disk SQLite database and return a fresh ``Database`` handle."""
    db_path = db.db_path if db and db.db_path else None
    path = reset_local_database(db_path)
    return path, Database(db_path)


@dataclass(frozen=True)
class CharacterDeleteResult:
    pipeline_id: int
    asset_name: str
    deleted_output_dirs: tuple[Path, ...]


def _legacy_character_output_root(project: Project, pipe: Pipeline) -> Path | None:
    legacy_slug = pipe.metadata.get("output_slug")
    if not isinstance(legacy_slug, str) or not legacy_slug.strip():
        return None
    return (
        Path(project.output_root)
        / project_output_slug(project)
        / "Characters"
        / legacy_slug.strip()
    )


def character_output_dirs_for_delete(project: Project, pipe: Pipeline) -> list[Path]:
    """Return distinct on-disk output folders that may belong to a character."""
    candidates = [
        Path(project.output_root) / folder_output_slug(project, pipe),
        character_output_root(project, pipe),
    ]
    legacy = _legacy_character_output_root(project, pipe)
    if legacy is not None:
        candidates.append(legacy)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def delete_character(db: Database, pipeline_id: int) -> CharacterDeleteResult:
    """Delete a character's pipeline row and all output folders on disk."""
    pipe = db.get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError(f"Pipeline {pipeline_id} not found")
    project = db.get_project(pipe.project_id)
    if not project:
        raise ValueError(f"Project {pipe.project_id} not found for pipeline {pipeline_id}")

    ensure_pipeline_output_slug(db, pipeline_id)
    pipe = db.get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError(f"Pipeline {pipeline_id} not found")

    deleted_dirs: list[Path] = []
    for folder in character_output_dirs_for_delete(project, pipe):
        if not folder.exists():
            continue
        delete_output_directory(folder)
        deleted_dirs.append(folder.resolve())

    asset_name = pipe.asset_name
    if not db.delete_pipeline(pipeline_id):
        raise ValueError(f"Pipeline {pipeline_id} not found")

    return CharacterDeleteResult(
        pipeline_id=pipeline_id,
        asset_name=asset_name,
        deleted_output_dirs=tuple(deleted_dirs),
    )


@dataclass(frozen=True)
class ProjectDeleteResult:
    project_id: int
    project_name: str
    pipeline_count: int


def delete_project(db: Database, project_id: int) -> ProjectDeleteResult:
    """Delete a project row and all associated pipeline DB records (CASCADE)."""
    project = db.get_project(project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")
    pipelines = db.list_pipelines_for_project(project_id)
    pipeline_count = len(pipelines)
    if not db.delete_project(project_id):
        raise ValueError(f"Project {project_id} not found")
    return ProjectDeleteResult(
        project_id=project_id,
        project_name=project.name,
        pipeline_count=pipeline_count,
    )
