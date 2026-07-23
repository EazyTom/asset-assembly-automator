"""Detect missing on-disk Meshy workflow assets and suggest a re-run stage."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from asset_assembly_automator.core.db.models import Database, Pipeline
from asset_assembly_automator.core.output_paths import (
    get_output_dirs,
    pipeline_output_slug,
    tpose_approved_path,
)
from asset_assembly_automator.core.state_machine import MESHY_WORKFLOW_STAGE_ORDER, StageId


@dataclass(frozen=True)
class MeshyAssetHealth:
    assets_present: bool
    missing: list[str] = field(default_factory=list)
    rerun_stage: StageId | None = None
    message: str = ""


def _meshy_workflow_index(stage: StageId) -> int:
    try:
        return MESHY_WORKFLOW_STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def _resolve_source_image(
    db: Database, pipeline_id: int, pipe: Pipeline, dirs: dict[str, Path]
) -> Path | None:
    for key in ("source_image_path", "source_drop_path"):
        raw = pipe.metadata.get(key)
        if raw:
            path = Path(str(raw))
            if path.is_file():
                return path
    for row in db.get_assets(pipeline_id, "tpose"):
        path = Path(str(row["file_path"]))
        if path.is_file():
            return path
    candidate = tpose_approved_path(dirs, pipeline_output_slug(pipe))
    if candidate.is_file():
        return candidate
    return None


def _rig_fbx_present(pipe: Pipeline, dirs: dict[str, Path]) -> bool:
    if dirs["source"].is_dir() and any(dirs["source"].glob("*.fbx")):
        return True
    primary = pipe.metadata.get("primary_rig_fbx")
    return bool(primary and Path(str(primary)).is_file())


def _textures_present(dirs: dict[str, Path]) -> bool:
    return dirs["textures"].is_dir() and bool(list(dirs["textures"].glob("*.png")))


def _meshy_zip_present(pipe: Pipeline) -> bool:
    zip_path = pipe.metadata.get("meshy_export_zip")
    return bool(zip_path and Path(str(zip_path)).is_file())


def _expects_meshy_deliverables(pipe: Pipeline) -> bool:
    current = StageId(pipe.current_stage)
    if current == StageId.COMPLETE:
        return True
    download_idx = _meshy_workflow_index(StageId.MESHY_DOWNLOAD)
    if _meshy_workflow_index(current) >= download_idx:
        return True
    return bool(
        pipe.metadata.get("rig_task_id")
        or pipe.metadata.get("downloaded_paths")
        or pipe.metadata.get("primary_rig_fbx")
        or pipe.metadata.get("meshy_export_zip")
    )


def assess_meshy_asset_health(db: Database, pipeline_id: int) -> MeshyAssetHealth:
    pipe = db.get_pipeline(pipeline_id)
    if not pipe:
        return MeshyAssetHealth(True)

    if pipe.metadata.get("workflow") != "meshy_drop":
        return MeshyAssetHealth(True)

    try:
        dirs = get_output_dirs(db, pipeline_id)
    except ValueError:
        return MeshyAssetHealth(
            assets_present=False,
            missing=["pipeline"],
            rerun_stage=StageId.IMAGE_PREP,
            message="Pipeline or project not found",
        )

    missing: list[str] = []
    if not dirs["root"].is_dir():
        missing.append("output_folder")

    source_image = _resolve_source_image(db, pipeline_id, pipe, dirs)
    if source_image is None:
        missing.append("source_image")

    if _expects_meshy_deliverables(pipe):
        if not _rig_fbx_present(pipe, dirs):
            missing.append("rig_fbx")
        if not _textures_present(dirs):
            missing.append("textures")
        if not _meshy_zip_present(pipe):
            missing.append("meshy_zip")

    if not missing:
        return MeshyAssetHealth(assets_present=True)

    if "source_image" in missing or "output_folder" in missing:
        rerun = StageId.IMAGE_PREP
    elif pipe.metadata.get("rig_task_id"):
        rerun = StageId.MESHY_DOWNLOAD
    else:
        rerun = StageId.MESHY_I2D

    readable = ", ".join(m.replace("_", " ") for m in missing)
    return MeshyAssetHealth(
        assets_present=False,
        missing=missing,
        rerun_stage=rerun,
        message=f"Missing on disk: {readable}. Re-run Meshy from {rerun.value.replace('_', ' ')}.",
    )
