from __future__ import annotations

import argparse
import contextvars
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from asset_assembly_automator.clients.cursor_cli_client import CursorCliClient, FakeCursorCliClient
from asset_assembly_automator.clients.higgsfield_client import create_higgsfield_client
from asset_assembly_automator.clients.magnific_client import create_magnific_client
from asset_assembly_automator.clients.meshy_client import FakeMeshyClient, MeshyClient
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
        cfg["ai_model"] = "meshy-t2"
        cfg["target_polycount"] = int(meta.get("smart_topology_polycount", 4000))
        cfg.pop("topology", None)
        cfg.pop("hd_texture", None)
        cfg.pop("texture_resolution", None)
        cfg.pop("remove_lighting", None)
        cfg.pop("ultra_mode", None)
    else:
        cfg["model_type"] = "standard"
        cfg["ai_model"] = meta.get("ai_model", settings.meshy.ai_model)
        cfg["texture_resolution"] = meta.get(
            "texture_resolution", settings.meshy.default_texture_resolution
        )
        cfg.pop("hd_texture", None)
        budget_map = settings.meshy.i2d_target_polycount.model_dump()
        cfg["target_polycount"] = budget_map.get(pipe.poly_budget, budget_map["hero"])
        if meta.get("ultra_mode", settings.meshy.ultra_mode):
            cfg["ultra_mode"] = True
        if cfg.get("ai_model") != "meshy-6":
            cfg.pop("remove_lighting", None)

    if kind == "character":
        cfg["pose_mode"] = settings.meshy.pose_mode
    else:
        cfg.pop("pose_mode", None)

    return cfg


def remesh_target_for_pipeline(pipe: Pipeline) -> int:
    """Target polygon count for remesh stage from pipeline poly budget."""
    settings = get_settings()
    budget_map = settings.meshy.remesh_target_tris.model_dump()
    return int(budget_map.get(pipe.poly_budget, budget_map["hero"]))


async def resolve_meshy_job(
    client: MeshyClient | FakeMeshyClient,
    task_id: str,
    task_type: str,
    *,
    cancel_event: Any | None = None,
    writer: PipelineLogWriter | None = None,
) -> dict[str, Any]:
    """Poll a Meshy job until it reaches a terminal state when still in progress."""
    data = await client.get_task_status(task_id, task_type)
    status = data.get("status", "PENDING")
    if status not in ("SUCCEEDED", "FAILED", "CANCELED"):
        if writer:
            writer.log("info", f"Polling {task_type} job", task_id=task_id, status=status)
        data = await client.poll_until_done(task_id, task_type, cancel_event=cancel_event)
    return data


def meshy_face_count(result: dict[str, Any]) -> int | None:
    raw = result.get("face_count")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    nested = result.get("result") or {}
    if isinstance(nested, dict) and nested.get("face_count") is not None:
        try:
            return int(nested["face_count"])
        except (TypeError, ValueError):
            return None
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
