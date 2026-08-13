"""Safe, Windows-friendly output directory and file naming."""

from __future__ import annotations

import re
from pathlib import Path

from asset_assembly_automator.core.db.models import Database, Pipeline, Project

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def slugify_path_component(name: str, *, max_len: int = 48, fallback: str = "asset") -> str:
    """Convert a label to a lowercase path segment without spaces."""
    cleaned = re.sub(r"[^\w\-]+", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_").lower()
    if not cleaned:
        cleaned = fallback
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip("_")
    return cleaned or fallback


def display_name_from_filename(stem: str, *, max_len: int = 80) -> str:
    """Human-readable asset name for UI (spaces allowed, UUID suffixes removed)."""
    text = _UUID_RE.sub("", stem)
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = "Character"
    if len(text) > max_len:
        text = text[:max_len].rstrip()
    return text


def project_output_slug(project: Project) -> str:
    return slugify_path_component(project.name, max_len=64, fallback=f"project_{project.id}")


def character_name_slug(name: str) -> str:
    """Slug for a character display name (same rules as project slug)."""
    return slugify_path_component(name, max_len=32, fallback="character")


def _legacy_character_slug_from_metadata(pipe: Pipeline) -> str | None:
    legacy = pipe.metadata.get("output_slug")
    if not isinstance(legacy, str) or not legacy.strip():
        return None
    legacy = legacy.strip()
    if legacy.startswith("chr_"):
        parts = legacy.split("_", 2)
        if len(parts) == 3 and parts[2]:
            return parts[2]
    return legacy


def pipeline_character_slug(pipe: Pipeline) -> str:
    """Stable character slug used in dropdowns, file prefixes, and folder names."""
    stored = pipe.metadata.get("character_slug")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    legacy = _legacy_character_slug_from_metadata(pipe)
    if legacy:
        return legacy
    return character_name_slug(pipe.asset_name)


def folder_output_slug(project: Project, pipe: Pipeline) -> str:
    """Output directory name: {project_slug}-{character_slug}."""
    stored = pipe.metadata.get("folder_slug")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    return f"{project_output_slug(project)}-{pipeline_character_slug(pipe)}"


def pipeline_output_slug(pipe: Pipeline) -> str:
    """Character slug for file prefixes and Unity import paths."""
    return pipeline_character_slug(pipe)


def chr_file_prefix(character_slug: str) -> str:
    return f"CHR_{character_slug}"


def asset_file_prefix(asset_kind: str, slug: str) -> str:
    if asset_kind == "vehicle":
        return f"VEH_{slug}"
    if asset_kind == "aircraft":
        return f"AIR_{slug}"
    return chr_file_prefix(slug)


def approved_folder_name(asset_kind: str) -> str:
    if asset_kind == "character":
        return "TPose"
    return "Approved"


def approved_concept_path(dirs: dict[str, Path], slug: str, asset_kind: str = "character") -> Path:
    folder_key = "tpose" if asset_kind == "character" else "approved"
    if folder_key == "approved" and "approved" not in dirs:
        approved_dir = dirs["root"] / approved_folder_name(asset_kind)
        return approved_dir / f"{asset_file_prefix(asset_kind, slug)}_Approved_v01.png"
    prefix = asset_file_prefix(asset_kind, slug)
    if asset_kind == "character":
        return dirs["tpose"] / f"{prefix}_TPose_Approved_v01.png"
    approved_dir = dirs.get("approved") or (dirs["root"] / "Approved")
    return approved_dir / f"{prefix}_Approved_v01.png"


def project_output_root(project: Project) -> Path:
    """Project-level output root (used when no character is selected)."""
    return Path(project.output_root) / project_output_slug(project)


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


def character_output_root(project: Project, pipe: Pipeline) -> Path:
    folder = folder_output_slug(project, pipe)
    new_root = Path(project.output_root) / folder
    if new_root.exists():
        return new_root
    legacy = _legacy_character_output_root(project, pipe)
    if legacy and legacy.exists():
        return legacy
    return new_root


def ensure_pipeline_output_slug(db: Database, pipeline_id: int) -> str:
    pipe = db.get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError(f"Pipeline {pipeline_id} not found")
    project = db.get_project(pipe.project_id)
    if not project:
        raise ValueError(f"Project {pipe.project_id} not found for pipeline {pipeline_id}")

    char_slug = character_name_slug(pipe.asset_name)
    folder = f"{project_output_slug(project)}-{char_slug}"
    meta = {**pipe.metadata, "character_slug": char_slug, "folder_slug": folder}
    if meta != pipe.metadata:
        db.update_pipeline_stage(
            pipeline_id,
            pipe.current_stage,
            metadata=meta,
        )
    return folder


def get_output_dirs_for(project: Project, pipe: Pipeline) -> dict[str, Path]:
    root = character_output_root(project, pipe)
    kind = getattr(pipe, "asset_kind", None) or pipe.metadata.get("asset_kind") or "character"
    dirs = {
        "root": root,
        "concept": root / "Concept",
        "tpose": root / "TPose",
        "source": root / "Source",
        "animations": root / "Animations",
        "textures": root / "Textures",
        "previews": root / "Previews",
    }
    if kind != "character":
        dirs["approved"] = root / "Approved"
    return dirs


def get_output_dirs(db: Database, pipeline_id: int) -> dict[str, Path]:
    pipe = db.get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError(f"Pipeline {pipeline_id} not found")
    project = db.get_project(pipe.project_id)
    if not project:
        raise ValueError(f"Project {pipe.project_id} not found")
    ensure_pipeline_output_slug(db, pipeline_id)
    pipe = db.get_pipeline(pipeline_id)
    assert pipe is not None
    return get_output_dirs_for(project, pipe)


def tpose_approved_path(dirs: dict[str, Path], character_slug: str) -> Path:
    return dirs["tpose"] / f"{chr_file_prefix(character_slug)}_TPose_Approved_v01.png"


def preview_png_path(dirs: dict[str, Path], character_slug: str) -> Path:
    return dirs["previews"] / f"{chr_file_prefix(character_slug)}_mesh_preview.png"


def preview_glb_path(dirs: dict[str, Path]) -> Path:
    return dirs["source"] / "Character_preview.glb"
