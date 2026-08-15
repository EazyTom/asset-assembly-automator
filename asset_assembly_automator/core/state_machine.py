from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from asset_assembly_automator.core.db.models import Database, Pipeline


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
    MESHY_REMESH = "meshy_remesh"
    MESHY_RIG = "meshy_rig"
    MESHY_ANIMATE = "meshy_animate"
    MESHY_DOWNLOAD = "meshy_download"
    MESHY_QC = "meshy_qc"
    PACKAGE_EXPORT = "package_export"
    COMPLETE = "complete"
    # Phase 2 stubs
    WORLD_CONCEPT = "world_concept"
    WORLD_I2D = "world_i2d"
    WORLD_REMESH = "world_remesh"
    WORLD_EXPORT = "world_export"
    UNITY_IMPORT = "unity_import"


CHARACTER_STAGE_ORDER: list[StageId] = [
    StageId.DRAFT,
    StageId.PROMPT_BUILD,
    StageId.CONCEPT_REVIEW,
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
    StageId.COMPLETE,
]

VEHICLE_STAGE_ORDER: list[StageId] = [
    StageId.DRAFT,
    StageId.PROMPT_BUILD,
    StageId.CONCEPT_REVIEW,
    StageId.MAGNIFIC_UPREZ,
    StageId.IMAGE_PREP,
    StageId.MESHY_I2D,
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
    if kind not in ("character", "vehicle", "aircraft"):
        return "character"
    return kind


def stage_order_for_kind(asset_kind: str) -> list[StageId]:
    if asset_kind == "vehicle":
        return list(VEHICLE_STAGE_ORDER)
    if asset_kind == "aircraft":
        return list(AIRCRAFT_STAGE_ORDER)
    return list(CHARACTER_STAGE_ORDER)


def runnable_stage(current: StageId) -> StageId:
    """Map non-executable placeholders to the first real stage."""
    if current == StageId.DRAFT:
        return StageId.PROMPT_BUILD
    return current


def _effective_order(*, asset_kind: str = "character", multi_view: bool = False) -> list[StageId]:
    order = stage_order_for_kind(asset_kind)
    if not multi_view and StageId.TURNAROUND in order:
        order = [s for s in order if s != StageId.TURNAROUND]
    return order


def next_stage(
    current: StageId,
    *,
    multi_view: bool = False,
    asset_kind: str = "character",
) -> StageId | None:
    order = _effective_order(asset_kind=asset_kind, multi_view=multi_view)
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


def can_transition(
    current: StageId,
    target: StageId,
    *,
    asset_kind: str = "character",
) -> bool:
    order = stage_order_for_kind(asset_kind)
    try:
        return order.index(target) >= order.index(current)
    except ValueError:
        return False


def advance_pipeline(
    db: Database,
    pipeline_id: int,
    *,
    multi_view: bool = False,
) -> StageId | None:
    pipe = db.get_pipeline(pipeline_id)
    if not pipe:
        return None
    kind = asset_kind_for_pipeline(pipe)
    current = StageId(pipe.current_stage)
    nxt = next_stage(current, multi_view=multi_view or pipe.multi_view, asset_kind=kind)
    if nxt:
        db.update_pipeline_stage(pipeline_id, nxt.value)
    return nxt
