from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from asset_assembly_automator.core.config import get_settings

_local = threading.local()


@dataclass
class Project:
    id: int
    name: str
    pipeline_type: str
    unity_project_path: str | None
    output_root: str
    created_at: str


@dataclass
class Pipeline:
    id: int
    project_id: int
    asset_name: str
    current_stage: str
    status: str
    selected_concept_provider: str | None
    selected_concept_asset_id: int | None
    rig_provider: str
    poly_budget: str
    multi_view: bool
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass
class StageResult:
    success: bool
    stage: str
    message: str = ""
    next_stage: str | None = None
    data: dict[str, Any] | None = None
    error: str | None = None


def _schema_path() -> Path:
    return Path(__file__).resolve().parent / "schema.sql"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    settings = get_settings()
    path = db_path or (settings.paths.app_data / "aaa.db")
    path_key = str(path.resolve())
    if hasattr(_local, "conn") and _local.conn is not None:
        if getattr(_local, "conn_path", None) == path_key:
            return _local.conn
        _local.conn.close()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    _local.conn = conn
    _local.conn_path = path_key
    return conn


def close_thread_connection() -> None:
    """Close the thread-local SQLite handle (required before deleting aaa.db on disk)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
    _local.conn = None
    _local.conn_path = None


def local_database_path(db_path: Path | None = None) -> Path:
    settings = get_settings()
    return db_path or (settings.paths.app_data / "aaa.db")


def reset_local_database(db_path: Path | None = None) -> Path:
    """Delete the local aaa.db (and WAL sidecars) and recreate an empty schema."""
    path = local_database_path(db_path)
    close_thread_connection()
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            candidate.unlink()
    init_db(path)
    return path


def init_db(db_path: Path | None = None) -> None:
    conn = get_connection(db_path)
    schema = _schema_path().read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()


@contextmanager
def transaction(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _row_to_pipeline(row: sqlite3.Row) -> Pipeline:
    return Pipeline(
        id=row["id"],
        project_id=row["project_id"],
        asset_name=row["asset_name"],
        current_stage=row["current_stage"],
        status=row["status"],
        selected_concept_provider=row["selected_concept_provider"],
        selected_concept_asset_id=row["selected_concept_asset_id"],
        rig_provider=row["rig_provider"],
        poly_budget=row["poly_budget"],
        multi_view=bool(row["multi_view"]),
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class Database:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path
        init_db(db_path)

    @property
    def conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    def create_project(
        self,
        name: str,
        output_root: str,
        *,
        pipeline_type: str = "character",
        unity_project_path: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO projects (name, pipeline_type, unity_project_path, output_root)
            VALUES (?, ?, ?, ?)
            """,
            (name, pipeline_type, unity_project_path, output_root),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def create_pipeline(
        self,
        project_id: int,
        asset_name: str,
        *,
        poly_budget: str = "hero",
        multi_view: bool = False,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO pipelines (project_id, asset_name, poly_budget, multi_view, current_stage)
            VALUES (?, ?, ?, ?, 'draft')
            """,
            (project_id, asset_name, poly_budget, int(multi_view)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_pipeline(self, pipeline_id: int) -> Pipeline | None:
        row = self.conn.execute("SELECT * FROM pipelines WHERE id = ?", (pipeline_id,)).fetchone()
        return _row_to_pipeline(row) if row else None

    def delete_pipeline(self, pipeline_id: int) -> bool:
        """Delete a pipeline and all related rows (CASCADE). Returns False if missing."""
        cur = self.conn.execute("DELETE FROM pipelines WHERE id = ?", (pipeline_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def delete_project(self, project_id: int) -> bool:
        """Delete a project and all pipelines/related rows (CASCADE). Returns False if missing."""
        cur = self.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def list_pipelines(self, *, status: str | None = None) -> list[Pipeline]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM pipelines WHERE status = ? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM pipelines ORDER BY updated_at DESC").fetchall()
        return [_row_to_pipeline(r) for r in rows]

    def list_pipelines_for_project(
        self,
        project_id: int,
        *,
        workflow: str | None = None,
    ) -> list[Pipeline]:
        rows = self.conn.execute(
            "SELECT * FROM pipelines WHERE project_id = ? ORDER BY updated_at DESC",
            (project_id,),
        ).fetchall()
        pipes = [_row_to_pipeline(r) for r in rows]
        if workflow:
            pipes = [p for p in pipes if p.metadata.get("workflow") == workflow]
        return pipes

    def update_pipeline_poly_budget(self, pipeline_id: int, poly_budget: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "UPDATE pipelines SET poly_budget = ?, updated_at = ? WHERE id = ?",
            (poly_budget, now, pipeline_id),
        )
        self.conn.commit()

    def update_pipeline_asset_name(self, pipeline_id: int, asset_name: str) -> None:
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            "UPDATE pipelines SET asset_name = ?, updated_at = ? WHERE id = ?",
            (asset_name.strip(), now, pipeline_id),
        )
        self.conn.commit()

    def update_pipeline_stage(
        self,
        pipeline_id: int,
        stage: str,
        *,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        pipe = self.get_pipeline(pipeline_id)
        if not pipe:
            raise ValueError(f"Pipeline {pipeline_id} not found")
        meta = {**pipe.metadata, **(metadata or {})}
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """
            UPDATE pipelines
            SET current_stage = ?, status = COALESCE(?, status),
                metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (stage, status, json.dumps(meta), now, pipeline_id),
        )
        self.conn.commit()

    def record_stage(
        self,
        pipeline_id: int,
        stage_name: str,
        status: str,
        *,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        now = datetime.now(UTC).isoformat()
        started = now if status in ("in_progress", "queued") else None
        completed = now if status in ("completed", "failed", "skipped") else None
        cur = self.conn.execute(
            """
            INSERT INTO pipeline_stages
            (pipeline_id, stage_name, status, started_at, completed_at, error_message, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pipeline_id,
                stage_name,
                status,
                started,
                completed,
                error_message,
                json.dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_log(
        self,
        pipeline_id: int,
        level: str,
        message: str,
        *,
        stage_id: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO log_entries (pipeline_id, stage_id, level, message, context_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (pipeline_id, stage_id, level, message, json.dumps(context or {})),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def _parse_log_row(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        raw = data.get("context_json") or "{}"
        try:
            data["context"] = json.loads(raw)
        except json.JSONDecodeError:
            data["context"] = {}
        return data

    def get_logs_since(self, pipeline_id: int, since_id: int = 0) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM log_entries WHERE pipeline_id = ? AND id > ? ORDER BY id",
            (pipeline_id, since_id),
        ).fetchall()
        return [self._parse_log_row(r) for r in rows]

    def get_log_summary(self, pipeline_id: int) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) AS entry_count,
                MAX(created_at) AS last_at,
                (
                    SELECT message FROM log_entries
                    WHERE pipeline_id = ?
                    ORDER BY id DESC LIMIT 1
                ) AS last_message
            FROM log_entries
            WHERE pipeline_id = ?
            """,
            (pipeline_id, pipeline_id),
        ).fetchone()
        return dict(row) if row else {"entry_count": 0, "last_at": None, "last_message": None}

    def get_setting(
        self, key: str, scope: str = "global", default: str | None = None
    ) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ? AND scope = ?",
            (key, scope),
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str, scope: str = "global") -> None:
        self.conn.execute(
            """
            INSERT INTO settings (key, value, scope) VALUES (?, ?, ?)
            ON CONFLICT(key, scope) DO UPDATE SET value = excluded.value
            """,
            (key, value, scope),
        )
        self.conn.commit()

    def save_prompt(
        self,
        pipeline_id: int,
        provider: str,
        final_text: str,
        *,
        template_id: str | None = None,
        template_vars: dict[str, Any] | None = None,
        stage_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO prompts (pipeline_id, stage_id, provider, template_id, final_text, template_vars_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                pipeline_id,
                stage_id,
                provider,
                template_id,
                final_text,
                json.dumps(template_vars or {}),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_asset(
        self,
        pipeline_id: int,
        asset_type: str,
        file_path: str,
        *,
        provider: str | None = None,
        thumb_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        stage_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO assets (pipeline_id, stage_id, asset_type, file_path, thumb_path, provider, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pipeline_id,
                stage_id,
                asset_type,
                file_path,
                thumb_path,
                provider,
                json.dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_assets(self, pipeline_id: int, asset_type: str | None = None) -> list[dict[str, Any]]:
        if asset_type:
            rows = self.conn.execute(
                "SELECT * FROM assets WHERE pipeline_id = ? AND asset_type = ? ORDER BY id DESC",
                (pipeline_id, asset_type),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM assets WHERE pipeline_id = ? ORDER BY id DESC",
                (pipeline_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def save_external_job(
        self,
        pipeline_id: int,
        provider: str,
        task_id: str,
        task_type: str,
        *,
        status: str = "PENDING",
        face_count: int | None = None,
        credits_used: float = 0,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO external_jobs
            (pipeline_id, provider, task_id, task_type, status, face_count, credits_used, expires_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pipeline_id,
                provider,
                task_id,
                task_type,
                status,
                face_count,
                credits_used,
                expires_at,
                json.dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_external_job(
        self, pipeline_id: int, task_type: str, *, active_only: bool = True
    ) -> dict[str, Any] | None:
        query = """
            SELECT * FROM external_jobs
            WHERE pipeline_id = ? AND task_type = ?
        """
        params: list[Any] = [pipeline_id, task_type]
        if active_only:
            query += " AND status NOT IN ('FAILED', 'CANCELED', 'SUCCEEDED')"
        query += " ORDER BY id DESC LIMIT 1"
        row = self.conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def update_external_job(
        self,
        job_id: int,
        *,
        status: str | None = None,
        face_count: int | None = None,
        credits_used: float | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if face_count is not None:
            fields.append("face_count = ?")
            values.append(face_count)
        if credits_used is not None:
            fields.append("credits_used = ?")
            values.append(credits_used)
        if not fields:
            return
        values.append(job_id)
        self.conn.execute(
            f"UPDATE external_jobs SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        self.conn.commit()

    def get_project(self, project_id: int) -> Project | None:
        row = self.conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            return None
        return Project(
            id=row["id"],
            name=row["name"],
            pipeline_type=row["pipeline_type"],
            unity_project_path=row["unity_project_path"],
            output_root=row["output_root"],
            created_at=row["created_at"],
        )

    def list_projects(self) -> list[Project]:
        rows = self.conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [
            Project(
                id=row["id"],
                name=row["name"],
                pipeline_type=row["pipeline_type"],
                unity_project_path=row["unity_project_path"],
                output_root=row["output_root"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def update_project(
        self,
        project_id: int,
        *,
        name: str | None = None,
        output_root: str | None = None,
        unity_project_path: str | None = None,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []
        if name is not None:
            fields.append("name = ?")
            values.append(name)
        if output_root is not None:
            fields.append("output_root = ?")
            values.append(output_root)
        if unity_project_path is not None:
            fields.append("unity_project_path = ?")
            values.append(unity_project_path)
        if not fields:
            return
        values.append(project_id)
        self.conn.execute(
            f"UPDATE projects SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        self.conn.commit()

    def get_animation_selections(self, pipeline_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM animation_selections WHERE pipeline_id = ?",
            (pipeline_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_animation_selections(self, pipeline_id: int, selections: list[dict[str, Any]]) -> None:
        self.conn.execute(
            "DELETE FROM animation_selections WHERE pipeline_id = ?",
            (pipeline_id,),
        )
        for sel in selections:
            self.conn.execute(
                """
                INSERT INTO animation_selections
                (pipeline_id, action_id, action_name, is_default_included)
                VALUES (?, ?, ?, ?)
                """,
                (
                    pipeline_id,
                    sel["action_id"],
                    sel["action_name"],
                    int(sel.get("is_default_included", 0)),
                ),
            )
        self.conn.commit()
