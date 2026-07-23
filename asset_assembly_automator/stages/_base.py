from __future__ import annotations

import argparse
import contextvars
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
    """Map smart_topology config + poly budget to Meshy model_type for i2d."""
    settings = get_settings()
    smart = settings.meshy.smart_topology
    if smart == "lowpoly":
        return "lowpoly"
    if smart == "off":
        return settings.meshy.model_type
    if pipe.poly_budget in ("npc", "crowd"):
        return "lowpoly"
    return settings.meshy.model_type


def meshy_settings_for_pipeline(pipe: Pipeline) -> dict[str, Any]:
    """Resolve Meshy API settings for a pipeline, including budget-aware i2d polycount."""
    settings = get_settings()
    cfg = settings.meshy.model_dump()
    budget_map = settings.meshy.i2d_target_polycount.model_dump()
    cfg["target_polycount"] = budget_map.get(pipe.poly_budget, budget_map["hero"])
    cfg["model_type"] = resolve_i2d_model_type(pipe)
    cfg["target_formats"] = list(cfg.get("i2d_target_formats") or ["fbx", "glb"])
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
    ctx = StageContext(
        pipeline_id=pipeline_id,
        dry_run=dry_run,
        force_new=force_new,
        verbose=verbose,
        extra=dict(kwargs),
    )
    dirs = get_output_dirs(db, pipeline_id)
    writer = PipelineLogWriter(
        pipeline_id,
        stage_name,
        output_root=dirs["root"],
        db_callback=lambda lvl, msg, extra: db.add_log(pipeline_id, lvl, msg, context=extra),
    )
    db.record_stage(pipeline_id, stage_name, "in_progress")
    writer.log("info", f"Starting stage {stage_name}")
    try:
        result: StageResult = await fn(ctx, db, dirs, writer)
        db.record_stage(
            pipeline_id,
            stage_name,
            "completed" if result.success else "failed",
            error_message=result.error,
        )
        if result.next_stage:
            db.update_pipeline_stage(pipeline_id, result.next_stage)
        writer.log("info" if result.success else "error", result.message)
        return result
    except Exception as exc:
        message = format_stage_error(exc)
        db.record_stage(pipeline_id, stage_name, "failed", error_message=message)
        writer.log("error", message)
        return StageResult(success=False, stage=stage_name, error=message, message=message)
