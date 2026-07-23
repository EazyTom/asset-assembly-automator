"""Bootstrap helpers for the Meshy drop workflow app."""

from __future__ import annotations

import json
from pathlib import Path
from shutil import copy2
from typing import Any

from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.output_paths import (
    ensure_pipeline_output_slug,
    get_output_dirs,
    pipeline_output_slug,
    tpose_approved_path,
)
from asset_assembly_automator.core.state_machine import StageId


def find_workflow_pipeline(db: Database, project_id: int, asset_name: str) -> int | None:
    """Return an in-progress meshy_drop pipeline id for this project/asset, if any."""
    for pipe in db.list_pipelines_for_project(project_id, workflow="meshy_drop"):
        if pipe.asset_name == asset_name and pipe.status != "complete":
            return pipe.id
    return None


def workflow_asset_name_exists(db: Database, project_id: int, asset_name: str) -> bool:
    """True if any meshy_drop pipeline in the project already uses this asset name."""
    target = asset_name.strip().casefold()
    for pipe in db.list_pipelines_for_project(project_id, workflow="meshy_drop"):
        if pipe.asset_name.strip().casefold() == target:
            return True
    return False


def create_empty_meshy_pipeline(
    db: Database,
    project_id: int,
    asset_name: str,
    *,
    poly_budget: str = "hero",
    texture_prompt: str = "",
) -> int:
    """Create a meshy_drop pipeline + output dirs without a dropped image yet.

    Used by the workflow app's "New…" button so a character can be registered
    before T-pose art is available. Drop art later and Save/Run Meshy.
    """
    pipeline_id = db.create_pipeline(
        project_id,
        asset_name.strip(),
        poly_budget=poly_budget,
        multi_view=False,
    )
    ensure_pipeline_output_slug(db, pipeline_id)

    # Materialize output directories so the folder structure exists up front.
    dirs = get_output_dirs(db, pipeline_id)
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)

    pipe = db.get_pipeline(pipeline_id)
    metadata: dict[str, Any] = {
        **(pipe.metadata if pipe else {}),
        "workflow": "meshy_drop",
        "selected_concept_provider": "import",
        "meshy_texture_prompt": texture_prompt.strip(),
    }
    db.update_pipeline_poly_budget(pipeline_id, poly_budget)
    db.update_pipeline_stage(pipeline_id, StageId.DRAFT.value, metadata=metadata)
    return pipeline_id


def bootstrap_meshy_pipeline(
    db: Database,
    project_id: int,
    asset_name: str,
    image_path: str | Path,
    *,
    poly_budget: str = "hero",
    texture_prompt: str = "",
    existing_pipeline_id: int | None = None,
) -> int:
    """Copy dropped art into TPose/, record assets + metadata, return pipeline id."""
    source = Path(image_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Source image not found: {source}")

    pipeline_id = existing_pipeline_id or find_workflow_pipeline(db, project_id, asset_name)
    if pipeline_id is None:
        pipeline_id = db.create_pipeline(
            project_id,
            asset_name,
            poly_budget=poly_budget,
            multi_view=False,
        )
    else:
        pipe = db.get_pipeline(pipeline_id)
        if pipe and pipe.asset_name != asset_name:
            db.update_pipeline_asset_name(pipeline_id, asset_name)

    ensure_pipeline_output_slug(db, pipeline_id)

    pipe = db.get_pipeline(pipeline_id)
    if pipe:
        db.update_pipeline_poly_budget(pipeline_id, poly_budget)
        db.update_pipeline_stage(
            pipeline_id,
            pipe.current_stage,
            metadata={
                **pipe.metadata,
                "meshy_texture_prompt": texture_prompt.strip(),
            },
        )

    metadata: dict[str, Any] = {
        "workflow": "meshy_drop",
        "meshy_texture_prompt": texture_prompt.strip(),
        "selected_concept_provider": "import",
        "source_drop_path": str(source),
    }

    dirs = get_output_dirs(db, pipeline_id)
    pipe_ref = db.get_pipeline(pipeline_id)
    if not pipe_ref:
        raise ValueError(f"Pipeline {pipeline_id} not found after bootstrap")
    output_slug = pipeline_output_slug(pipe_ref)
    approved = tpose_approved_path(dirs, output_slug)
    approved.parent.mkdir(parents=True, exist_ok=True)
    copy2(source, approved)
    metadata["source_image_path"] = str(approved)

    existing_tpose = db.get_assets(pipeline_id, "tpose")
    import_assets = [
        a for a in db.get_assets(pipeline_id, "concept") if a.get("provider") == "import"
    ]
    if not existing_tpose:
        db.add_asset(
            pipeline_id,
            "tpose",
            str(approved),
            provider="import",
            metadata={"role": "source_drop", "original_path": str(source)},
        )
    else:
        db.conn.execute(
            "UPDATE assets SET file_path = ?, metadata_json = ? WHERE id = ?",
            (
                str(approved),
                json.dumps({"role": "source_drop", "original_path": str(source)}),
                existing_tpose[0]["id"],
            ),
        )
        db.conn.commit()
        if import_assets:
            db.conn.execute(
                "UPDATE assets SET file_path = ?, metadata_json = ? WHERE id = ?",
                (
                    str(approved),
                    json.dumps({"role": "source_drop", "original_path": str(source)}),
                    import_assets[0]["id"],
                ),
            )
            db.conn.commit()

    if not import_assets:
        db.add_asset(
            pipeline_id,
            "concept",
            str(approved),
            provider="import",
            metadata={"role": "source_drop", "original_path": str(source)},
        )

    db.update_pipeline_stage(pipeline_id, StageId.IMAGE_PREP.value, metadata=metadata)
    return pipeline_id
