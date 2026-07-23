from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from asset_assembly_automator.core.config import get_settings


def _ensure_log_dir() -> Path:
    settings = get_settings()
    log_dir = settings.paths.app_data / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def configure_logging(*, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str, **bind: Any) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name).bind(**bind)


def pipeline_log_dir(output_root: Path, pipeline_id: int) -> Path:
    """On-disk log folder for a pipeline under its character output root."""
    path = output_root / "logs" / str(pipeline_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def pipeline_unified_log_path(output_root: Path, pipeline_id: int) -> Path:
    return pipeline_log_dir(output_root, pipeline_id) / "pipeline.jsonl"


class PipelineLogWriter:
    """Writes JSONL logs to disk (per-stage + unified pipeline file) and DB via callback."""

    def __init__(
        self,
        pipeline_id: int,
        stage: str,
        output_root: Path | None = None,
        db_callback: Any | None = None,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.stage = stage
        self.output_root = output_root
        self.db_callback = db_callback
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        base = output_root or _ensure_log_dir()
        log_dir = pipeline_log_dir(base, pipeline_id)
        self.path = log_dir / f"{stage}_{ts}.jsonl"
        self.unified_path = log_dir / "pipeline.jsonl"
        self._logger = get_logger("pipeline", pipeline_id=pipeline_id, stage=stage)

    def _write_jsonl(self, path: Path, entry: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + os.linesep)

    def log(self, level: str, message: str, **extra: Any) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "message": message,
            "pipeline_id": self.pipeline_id,
            "stage": self.stage,
            **extra,
        }
        self._write_jsonl(self.path, entry)
        self._write_jsonl(self.unified_path, entry)
        getattr(self._logger, level.lower(), self._logger.info)(message, **extra)
        if self.db_callback:
            self.db_callback(level, message, {"stage": self.stage, **extra})
