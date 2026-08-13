"""Aggregate per-stage and end-to-end pipeline timing into SQLite."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from asset_assembly_automator.core.db.models import Database

MESHY_STAGE_NAMES = frozenset(
    {
        "meshy_i2d",
        "meshy_remesh",
        "meshy_rig",
        "meshy_animate",
        "meshy_download",
        "meshy_qc",
    }
)
CONCEPT_STAGE_NAMES = frozenset(
    {
        "prompt_build",
        "concept_generate",
        "concept_review",
        "image_prep",
        "turnaround",
        "magnific_uprez",
    }
)


def _parse_duration_ms(row: dict[str, Any]) -> int | None:
    raw = row.get("duration_ms")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    meta_raw = row.get("metadata_json") or "{}"
    try:
        meta = json.loads(meta_raw)
    except json.JSONDecodeError:
        return None
    dm = meta.get("duration_ms")
    return int(dm) if dm is not None else None


def _latest_stage_durations(conn, pipeline_id: int) -> dict[str, int]:
    """Latest completed duration per stage_name (one row per stage run)."""
    rows = conn.execute(
        """
        SELECT id, stage_name, status, duration_ms, metadata_json, started_at, completed_at
        FROM pipeline_stages
        WHERE pipeline_id = ? AND status IN ('completed', 'failed', 'skipped')
        ORDER BY id ASC
        """,
        (pipeline_id,),
    ).fetchall()
    latest: dict[str, int] = {}
    for row in rows:
        duration = _parse_duration_ms(dict(row))
        if duration is None:
            continue
        latest[str(row["stage_name"])] = duration
    return latest


def _sum_keys(durations: dict[str, int], keys: frozenset[str]) -> int:
    return sum(durations.get(name, 0) for name in keys)


def rollup_pipeline_timing(
    db: Database,
    pipeline_id: int,
    *,
    unity_csharp_ms: int | None = None,
    trigger: str = "unity_import",
) -> dict[str, Any]:
    """Compute timing stats from pipeline_stages and persist to pipeline_timing_stats."""
    pipe = db.get_pipeline(pipeline_id)
    if not pipe:
        raise ValueError(f"Pipeline {pipeline_id} not found")

    durations = _latest_stage_durations(db.conn, pipeline_id)
    meshy_total = _sum_keys(durations, MESHY_STAGE_NAMES)
    concept_total = _sum_keys(durations, CONCEPT_STAGE_NAMES)
    magnific_ms = durations.get("magnific_uprez", 0)
    unity_stage_ms = durations.get("unity_import", 0)
    stage_total = sum(durations.values())

    pipeline_wall_ms: int | None = None
    try:
        created = datetime.fromisoformat(pipe.created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        pipeline_wall_ms = int((datetime.now(UTC) - created).total_seconds() * 1000)
    except (ValueError, TypeError):
        pipeline_wall_ms = None

    stats: dict[str, Any] = {
        "pipeline_id": pipeline_id,
        "recorded_at": datetime.now(UTC).isoformat(),
        "trigger": trigger,
        "pipeline_wall_ms": pipeline_wall_ms,
        "stage_total_ms": stage_total,
        "meshy_total_ms": meshy_total,
        "concept_ms": concept_total,
        "magnific_ms": magnific_ms,
        "unity_stage_ms": unity_stage_ms,
        "unity_csharp_ms": unity_csharp_ms,
        "stage_durations_json": durations,
    }

    db.upsert_pipeline_timing_stats(
        pipeline_id,
        pipeline_wall_ms=pipeline_wall_ms,
        stage_total_ms=stage_total,
        meshy_total_ms=meshy_total,
        concept_ms=concept_total,
        magnific_ms=magnific_ms,
        unity_stage_ms=unity_stage_ms,
        unity_csharp_ms=unity_csharp_ms,
        stage_durations_json=durations,
        trigger=trigger,
    )

    meta = {
        **pipe.metadata,
        "timing_stats": {
            "recorded_at": stats["recorded_at"],
            "trigger": trigger,
            "pipeline_wall_ms": pipeline_wall_ms,
            "stage_total_ms": stage_total,
            "meshy_total_ms": meshy_total,
            "unity_stage_ms": unity_stage_ms,
            "unity_csharp_ms": unity_csharp_ms,
        },
    }
    db.update_pipeline_stage(pipeline_id, pipe.current_stage, metadata=meta)
    return stats
