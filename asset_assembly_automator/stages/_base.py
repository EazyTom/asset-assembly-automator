from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from asset_assembly_automator.clients.cursor_cli_client import CursorCliClient, FakeCursorCliClient
from asset_assembly_automator.clients.higgsfield_client import create_higgsfield_client
from asset_assembly_automator.clients.magnific_client import create_magnific_client
from asset_assembly_automator.clients.meshy_client import (
    TERMINAL_STATUSES,
    FakeMeshyClient,
    MeshyClient,
    MeshyTaskCanceled,
    consumed_credits,
    describe_task_failure,
    is_transient_task_failure,
    task_error_info,
    task_output,
)
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import Database, Pipeline, StageResult
from asset_assembly_automator.core.logging import PipelineLogWriter, configure_logging
from asset_assembly_automator.core.output_paths import (
    get_output_dirs,
)
from asset_assembly_automator.core.state_machine import StageId, asset_kind_for_pipeline
from asset_assembly_automator.workflow.templates import (
    load_unity_cleanup_template,
    load_unity_import_template,
)

__all__ = [
    "load_unity_cleanup_template",
    "load_unity_import_template",
]

_db_override: contextvars.ContextVar[Database | None] = contextvars.ContextVar(
    "aaa_db_override", default=None
)
_cancel_event: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "aaa_cancel_event", default=None
)


@dataclass
class StageContext:
    pipeline_id: int
    dry_run: bool = False
    force_new: bool = False
    verbose: bool = False
    cancel_event: Any | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def get_db() -> Database:
    override = _db_override.get()
    if override is not None:
        return override
    return Database()


def bind_db(db: Database) -> contextvars.Token[Database | None]:
    return _db_override.set(db)


def unbind_db(token: contextvars.Token[Database | None]) -> None:
    _db_override.reset(token)


def bind_cancel_event(event: Any | None) -> contextvars.Token[Any | None]:
    return _cancel_event.set(event)


def unbind_cancel_event(token: contextvars.Token[Any | None]) -> None:
    _cancel_event.reset(token)


def current_cancel_event() -> Any | None:
    return _cancel_event.get()


def get_meshy_client(dry_run: bool = False) -> MeshyClient | FakeMeshyClient:
    return FakeMeshyClient() if dry_run else MeshyClient()


def resolve_i2d_model_type(pipe: Pipeline) -> str:
    """Map pipeline preset to Meshy model_type for i2d."""
    preset = pipe.metadata.get("meshy_preset", get_settings().meshy.default_preset)
    if preset == "game_ready":
        return "smart-topology"
    return "standard"


def meshy_settings_for_pipeline(pipe: Pipeline) -> dict[str, Any]:
    """Resolve Meshy API settings for a pipeline, including preset and budget-aware polycount."""
    settings = get_settings()
    meta = pipe.metadata
    preset = meta.get("meshy_preset", settings.meshy.default_preset)
    cfg = settings.meshy.model_dump()
    kind = asset_kind_for_pipeline(pipe)

    cfg["image_enhancement"] = meta.get("image_enhancement", settings.meshy.image_enhancement)
    cfg["enable_pbr"] = settings.meshy.enable_pbr
    cfg["should_texture"] = settings.meshy.should_texture
    cfg["should_remesh"] = False
    cfg["target_formats"] = list(cfg.get("i2d_target_formats") or ["fbx", "glb"])

    if preset == "game_ready":
        cfg["model_type"] = "smart-topology"
        cfg["ai_model"] = meta.get("smart_topology_model", settings.meshy.smart_topology_model)
        cfg["target_polycount"] = int(meta.get("smart_topology_polycount", 4000))
        cfg.pop("topology", None)
        cfg.pop("hd_texture", None)
        cfg.pop("texture_resolution", None)
        cfg.pop("remove_lighting", None)
        cfg.pop("ultra_mode", None)
        cfg.pop("geometry_resolution", None)
    else:
        cfg["model_type"] = "standard"
        cfg["ai_model"] = meta.get("ai_model", settings.meshy.ai_model)
        cfg["texture_resolution"] = meta.get(
            "texture_resolution", settings.meshy.default_texture_resolution
        )
        cfg.pop("hd_texture", None)
        budget_map = settings.meshy.i2d_target_polycount.model_dump()
        cfg["target_polycount"] = budget_map.get(pipe.poly_budget, budget_map["hero"])
        geometry = meta.get("geometry_resolution") or settings.meshy.geometry_resolution
        if geometry == "standard" and meta.get("ultra_mode", settings.meshy.ultra_mode):
            geometry = "2k"
        cfg["geometry_resolution"] = geometry
        cfg.pop("ultra_mode", None)
        if cfg.get("ai_model") != "meshy-6":
            cfg.pop("remove_lighting", None)

    if kind == "character":
        cfg["pose_mode"] = settings.meshy.pose_mode
    else:
        cfg.pop("pose_mode", None)

    return cfg


# Meshy rigging allows 380,000 triangles. Its remesh guidance is 300,000 triangles
# or 150,000 quads, because a quad face counts as two triangles.
_TRIANGLE_REMESH_CAP = 300_000
_QUAD_REMESH_CAP = 150_000


def remesh_target_for_pipeline(pipe: Pipeline) -> int:
    """Target polygon count for remesh, capped so the result can be rigged."""
    settings = get_settings()
    budget_map = settings.meshy.remesh_target_tris.model_dump()
    target = int(budget_map.get(pipe.poly_budget, budget_map["hero"]))
    cap = _QUAD_REMESH_CAP if settings.meshy.topology == "quad" else _TRIANGLE_REMESH_CAP
    return min(target, cap)


def _mark_canceled_job(db: Database | None, job_id: int | None, exc: MeshyTaskCanceled) -> None:
    if exc.deleted and db is not None and job_id is not None:
        db.update_external_job(job_id, status="CANCELED")


async def resolve_meshy_job(
    client: MeshyClient | FakeMeshyClient,
    task_id: str,
    task_type: str,
    *,
    cancel_event: Any | None = None,
    writer: PipelineLogWriter | None = None,
    db: Database | None = None,
    job_id: int | None = None,
) -> dict[str, Any]:
    """Poll a Meshy job until it reaches a terminal state when still in progress."""
    try:
        data = await client.get_task_status(task_id, task_type)
        status = data.get("status", "PENDING")
        if status not in TERMINAL_STATUSES:
            if writer:
                writer.log("info", f"Polling {task_type} job", task_id=task_id, status=status)
            data = await client.poll_until_done(task_id, task_type, cancel_event=cancel_event)
        return data
    except MeshyTaskCanceled as exc:
        _mark_canceled_job(db, job_id, exc)
        raise


def record_meshy_result(
    db: Database,
    job_id: int,
    result: dict[str, Any],
    *,
    face_count: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist a polled task's status, consumed credits, and failure details."""
    meta = dict(metadata or {})
    error = task_error_info(result)
    if error:
        meta["task_error"] = error
    db.update_external_job(
        job_id,
        status=result.get("status", "FAILED"),
        face_count=face_count,
        credits_used=consumed_credits(result),
        metadata=meta or None,
    )


TRANSIENT_RETRY_DELAY_SECONDS = 5.0


async def run_meshy_task(
    client: MeshyClient | FakeMeshyClient,
    db: Database,
    ctx: StageContext,
    writer: PipelineLogWriter,
    *,
    task_type: str,
    create: Callable[[], Awaitable[dict[str, Any]]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a Meshy task, record it in external_jobs, and poll it to a final status.

    A task that FAILS with a transient task_error (refunded by Meshy) is created again up
    to ``meshy.transient_task_retries`` times. Returns the final task with ``task_id`` and
    ``job_id`` added.
    """
    attempts = 1 + max(0, get_settings().meshy.transient_task_retries)
    for attempt in range(1, attempts + 1):
        created = await create()
        task_id = str(created["task_id"])
        job_id = db.save_external_job(
            ctx.pipeline_id, "meshy", task_id, task_type, metadata=metadata
        )
        recovered = bool(created.get("recovered"))
        suffix = " (found in task list after an uncertain create response)" if recovered else ""
        writer.log(
            "warning" if recovered else "info",
            f"Meshy {task_type} job created{suffix}",
            task_id=task_id,
            attempt=attempt,
            provider="meshy",
        )
        try:
            result = await client.poll_until_done(
                task_id,
                task_type,
                cancel_event=ctx.cancel_event,
                initial=created.get("task") if isinstance(created.get("task"), dict) else None,
            )
        except MeshyTaskCanceled as exc:
            _mark_canceled_job(db, job_id, exc)
            raise
        record_meshy_result(db, job_id, result)
        status = result.get("status", "FAILED")
        if status == "SUCCEEDED":
            writer.log(
                "info",
                f"Meshy {task_type} job succeeded",
                task_id=task_id,
                credits=consumed_credits(result),
                provider="meshy",
            )
        else:
            writer.log(
                "error",
                f"Meshy {task_type} job {describe_task_failure(result)}",
                task_id=task_id,
                provider="meshy",
                **task_error_info(result),
            )
        if attempt < attempts and is_transient_task_failure(result):
            writer.log(
                "warning",
                f"Creating a new {task_type} task after a transient Meshy failure",
                failed_task_id=task_id,
                provider="meshy",
            )
            await asyncio.sleep(TRANSIENT_RETRY_DELAY_SECONDS * attempt)
            continue
        return {**result, "task_id": task_id, "job_id": job_id}
    raise RuntimeError("unreachable")


def job_metadata(job: dict[str, Any] | None) -> dict[str, Any]:
    if not job:
        return {}
    if isinstance(job.get("metadata"), dict):
        return job["metadata"]
    try:
        parsed = json.loads(job.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def reusable_meshy_job(
    db: Database, pipeline_id: int, task_type: str, *, force_new: bool
) -> dict[str, Any] | None:
    """Latest job of this type worth reattaching to (not FAILED/CANCELED)."""
    if force_new:
        return None
    job = db.get_external_job(pipeline_id, task_type, active_only=False)
    if job and job.get("status") not in ("FAILED", "CANCELED"):
        return job
    return None


def mesh_source_for_pipeline(db: Database, pipe: Pipeline) -> dict[str, str] | None:
    """The mesh that feeds remesh/rig/download: the approved variant, else the latest i2d."""
    chosen = pipe.metadata.get("mesh_source")
    if isinstance(chosen, dict) and chosen.get("task_id") and chosen.get("task_type"):
        return {"task_id": str(chosen["task_id"]), "task_type": str(chosen["task_type"])}
    job = db.get_external_job(pipe.id, "image-to-3d", active_only=False)
    if job:
        return {"task_id": str(job["task_id"]), "task_type": "image-to-3d"}
    return None


def meshy_face_count(result: dict[str, Any]) -> int | None:
    for source in (result, task_output(result)):
        raw = source.get("face_count") if isinstance(source, dict) else None
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def get_higgsfield_client(dry_run: bool, output_dir: Path) -> Any:
    return create_higgsfield_client(dry_run, output_dir)


def get_magnific_client(dry_run: bool, output_dir: Path) -> Any:
    return create_magnific_client(dry_run, output_dir)


def get_cursor_cli_client(dry_run: bool = False) -> CursorCliClient | FakeCursorCliClient:
    return FakeCursorCliClient() if dry_run else CursorCliClient()


def render_prompt(template_path: Path, variables: dict[str, Any]) -> str:
    data = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    merged = {**defaults, **variables}
    return data["template"].format(**merged).replace("\n", " ").strip()


def load_template(template_name: str) -> dict[str, Any]:
    repo = Path(__file__).resolve().parents[2]
    path = repo / "config" / "prompt_templates" / template_name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def format_stage_error(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        parts = [format_stage_error(e) for e in exc.exceptions]
        return "; ".join(dict.fromkeys(parts))
    cause = exc.__cause__ or exc.__context__
    msg = str(exc).strip() or exc.__class__.__name__
    if cause and str(cause) not in msg:
        return f"{msg}: {format_stage_error(cause)}"
    return msg


def stage_argparser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--pipeline-id", type=int, required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--force-new", action="store_true")
    return p


async def run_stage(
    pipeline_id: int,
    stage_name: str,
    fn: Any,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    force_new: bool = False,
    **kwargs: Any,
) -> StageResult:
    configure_logging(verbose=verbose)
    db = get_db()
    pipe = db.get_pipeline(pipeline_id)
    ctx = StageContext(
        pipeline_id=pipeline_id,
        dry_run=dry_run,
        force_new=force_new,
        verbose=verbose,
        cancel_event=current_cancel_event(),
        extra=dict(kwargs),
    )
    dirs = get_output_dirs(db, pipeline_id)
    stage_id = db.record_stage(pipeline_id, stage_name, "in_progress")

    def _log_callback(lvl: str, msg: str, extra: dict[str, Any] | None = None) -> None:
        context = {**(extra or {}), "stage": stage_name}
        if pipe:
            context.setdefault("asset_name", pipe.asset_name)
            context.setdefault("asset_kind", asset_kind_for_pipeline(pipe))
        db.add_log(pipeline_id, lvl, msg, stage_id=stage_id, context=context)

    writer = PipelineLogWriter(
        pipeline_id,
        stage_name,
        output_root=dirs["root"],
        db_callback=_log_callback,
    )
    started = time.perf_counter()
    writer.log("info", f"Starting stage {stage_name}", stage_id=stage_id)
    try:
        result: StageResult = await fn(ctx, db, dirs, writer)
        duration_ms = int((time.perf_counter() - started) * 1000)
        db.record_stage(
            pipeline_id,
            stage_name,
            "completed" if result.success else "failed",
            stage_row_id=stage_id,
            duration_ms=duration_ms,
            error_message=result.error,
            metadata={"stage_id": stage_id},
        )
        if result.next_stage:
            db.update_pipeline_stage(pipeline_id, result.next_stage)
        finish_level = "info" if result.success else "error"
        writer.log(
            finish_level,
            result.message,
            duration_ms=duration_ms,
            stage_id=stage_id,
            success=result.success,
        )
        if stage_name == StageId.UNITY_IMPORT.value and result.success:
            from asset_assembly_automator.core.pipeline_timing import rollup_pipeline_timing

            unity_csharp_ms: int | None = None
            if isinstance(result.data, dict):
                raw = result.data.get("duration_ms")
                if raw is not None:
                    unity_csharp_ms = int(raw)
            stats = rollup_pipeline_timing(
                db,
                pipeline_id,
                unity_csharp_ms=unity_csharp_ms,
                trigger="unity_import",
            )
            writer.log(
                "info",
                "Pipeline timing stats recorded",
                pipeline_wall_ms=stats.get("pipeline_wall_ms"),
                meshy_total_ms=stats.get("meshy_total_ms"),
                unity_stage_ms=stats.get("unity_stage_ms"),
                stage_total_ms=stats.get("stage_total_ms"),
            )
        return result
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        message = format_stage_error(exc)
        db.record_stage(
            pipeline_id,
            stage_name,
            "failed",
            stage_row_id=stage_id,
            duration_ms=duration_ms,
            error_message=message,
            metadata={"stage_id": stage_id},
        )
        writer.log("error", message, duration_ms=duration_ms, stage_id=stage_id)
        return StageResult(success=False, stage=stage_name, error=message, message=message)
