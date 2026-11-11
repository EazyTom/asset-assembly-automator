from __future__ import annotations

import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from asset_assembly_automator.core.asset_kind import normalize_asset_kind

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from asset_assembly_automator.core.db.models import Pipeline


class StageId(StrEnum):
    DRAFT = "draft"
    PROMPT_BUILD = "prompt_build"
    # Optional: Refine / Use Higgs. Not on the auto path — preview native concepts first.
    CONCEPT_GENERATE = "concept_generate"
    CONCEPT_REVIEW = "concept_review"
    MAGNIFIC_UPREZ = "magnific_uprez"
    IMAGE_PREP = "image_prep"
    TURNAROUND = "turnaround"
    MESHY_I2D = "meshy_i2d"
    # Optional gate: pick the original i2d mesh or a retextured variant before remesh/rig.
    MESH_REVIEW = "mesh_review"
    # On-demand action at mesh_review; not on the auto path.
    MESHY_RETEXTURE = "meshy_retexture"
    MESHY_REMESH = "meshy_remesh"
    MESHY_RIG = "meshy_rig"
    MESHY_ANIMATE = "meshy_animate"
    MESHY_DOWNLOAD = "meshy_download"
    MESHY_QC = "meshy_qc"
    PACKAGE_EXPORT = "package_export"
    COMPLETE = "complete"
    UNITY_IMPORT = "unity_import"
    # Phase 2 stubs (world pipeline only)
    WORLD_CONCEPT = "world_concept"
    WORLD_I2D = "world_i2d"
    WORLD_REMESH = "world_remesh"
    WORLD_EXPORT = "world_export"


CHARACTER_STAGE_ORDER: list[StageId] = [
    StageId.DRAFT,
    StageId.PROMPT_BUILD,
    StageId.CONCEPT_REVIEW,
    StageId.MAGNIFIC_UPREZ,
    StageId.IMAGE_PREP,
    StageId.TURNAROUND,
    StageId.MESHY_I2D,
    StageId.MESH_REVIEW,
    StageId.MESHY_REMESH,
    StageId.MESHY_RIG,
    StageId.MESHY_ANIMATE,
    StageId.MESHY_DOWNLOAD,
    StageId.MESHY_QC,
    StageId.PACKAGE_EXPORT,
    StageId.COMPLETE,
]

VEHICLE_STAGE_ORDER: list[StageId] = [
    StageId.DRAFT,
    StageId.PROMPT_BUILD,
    StageId.CONCEPT_REVIEW,
    StageId.MAGNIFIC_UPREZ,
    StageId.IMAGE_PREP,
    StageId.MESHY_I2D,
    StageId.MESH_REVIEW,
    StageId.MESHY_REMESH,
    StageId.MESHY_DOWNLOAD,
    StageId.MESHY_QC,
    StageId.PACKAGE_EXPORT,
    StageId.COMPLETE,
]

AIRCRAFT_STAGE_ORDER: list[StageId] = [
    StageId.DRAFT,
    StageId.PROMPT_BUILD,
    StageId.CONCEPT_REVIEW,
    StageId.MAGNIFIC_UPREZ,
    StageId.IMAGE_PREP,
    StageId.MESHY_I2D,
    StageId.MESH_REVIEW,
    StageId.MESHY_REMESH,
    StageId.MESHY_DOWNLOAD,
    StageId.MESHY_QC,
    StageId.PACKAGE_EXPORT,
    StageId.COMPLETE,
]

MESHY_WORKFLOW_STAGE_ORDER: list[StageId] = [
    StageId.MAGNIFIC_UPREZ,
    StageId.IMAGE_PREP,
    StageId.MESHY_I2D,
    StageId.MESH_REVIEW,
    StageId.MESHY_REMESH,
    StageId.MESHY_RIG,
    StageId.MESHY_ANIMATE,
    StageId.MESHY_DOWNLOAD,
    StageId.MESHY_QC,
    StageId.PACKAGE_EXPORT,
    StageId.UNITY_IMPORT,
]

MANUAL_GATES = {
    StageId.CONCEPT_REVIEW,
    StageId.MESH_REVIEW,
}

AUTO_STAGES = {
    StageId.CONCEPT_GENERATE,
    StageId.MAGNIFIC_UPREZ,
    StageId.IMAGE_PREP,
    StageId.TURNAROUND,
    StageId.MESHY_I2D,
    StageId.MESHY_REMESH,
    StageId.MESHY_RIG,
    StageId.MESHY_ANIMATE,
    StageId.MESHY_DOWNLOAD,
    StageId.MESHY_QC,
    StageId.PACKAGE_EXPORT,
    StageId.UNITY_IMPORT,
}


def asset_kind_for_pipeline(pipe: Pipeline) -> str:
    kind = getattr(pipe, "asset_kind", None) or pipe.metadata.get("asset_kind") or "character"
    normalized = normalize_asset_kind(kind, strict=False)
    if normalized != kind:
        logger.warning(
            "Coerced unknown asset_kind %r to %r for pipeline %s", kind, normalized, pipe.id
        )
    return normalized


def stage_order_for_kind(asset_kind: str) -> list[StageId]:
    kind = normalize_asset_kind(asset_kind, strict=False)
    if kind == "vehicle":
        return list(VEHICLE_STAGE_ORDER)
    if kind == "aircraft":
        return list(AIRCRAFT_STAGE_ORDER)
    if kind != "character":
        logger.warning(
            "Unknown asset_kind %r in stage_order_for_kind; using character order", asset_kind
        )
    return list(CHARACTER_STAGE_ORDER)


def runnable_stage(current: StageId) -> StageId:
    """Map non-executable placeholders to the first real stage."""
    if current == StageId.DRAFT:
        return StageId.PROMPT_BUILD
    return current


def _effective_order(
    *,
    asset_kind: str = "character",
    multi_view: bool = False,
    mesh_review: bool = False,
) -> list[StageId]:
    order = stage_order_for_kind(asset_kind)
    if not multi_view and StageId.TURNAROUND in order:
        order = [s for s in order if s != StageId.TURNAROUND]
    if not mesh_review:
        order = [s for s in order if s != StageId.MESH_REVIEW]
    return order


def mesh_review_enabled(pipe: Pipeline) -> bool:
    from asset_assembly_automator.core.config import get_settings

    default = get_settings().meshy.mesh_review_gate
    return bool(pipe.metadata.get("mesh_review_enabled", default))


def next_stage(
    current: StageId,
    *,
    multi_view: bool = False,
    asset_kind: str = "character",
    mesh_review: bool = False,
) -> StageId | None:
    order = _effective_order(asset_kind=asset_kind, multi_view=multi_view, mesh_review=mesh_review)
    try:
        idx = order.index(current)
    except ValueError:
        return None
    if idx + 1 >= len(order):
        return None
    return order[idx + 1]


def stage_index(stage: StageId, *, asset_kind: str = "character") -> int:
    order = stage_order_for_kind(asset_kind)
    try:
        return order.index(stage)
    except ValueError:
        return -1


def stage_progress(stage: StageId, *, asset_kind: str = "character") -> int:
    order = stage_order_for_kind(asset_kind)
    idx = stage_index(stage, asset_kind=asset_kind)
    if idx < 0:
        return 0
    total = len(order) - 1
    return int((idx / total) * 100) if total else 0
