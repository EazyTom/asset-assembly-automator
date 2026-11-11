from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from asset_assembly_automator.core.asset_kind import (
    default_import_profile,
    display_label,
    normalize_asset_kind,
)
from asset_assembly_automator.core.db.models import Database, init_db


def test_normalize_asset_kind_display_labels():
    assert normalize_asset_kind("AAA Vehicle") == "vehicle"
    assert normalize_asset_kind("AAA Aircraft") == "aircraft"
    assert normalize_asset_kind("character") == "character"


def test_normalize_asset_kind_strict_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_asset_kind("veh", strict=True)


def test_display_label():
    assert display_label("vehicle") == "AAA Vehicle"


def test_default_import_profile():
    assert default_import_profile("vehicle") == "vehicle_drive_dashboard"


def test_create_pipeline_rejects_bad_kind(tmp_path):
    db_path = tmp_path / "aaa.db"
    db = Database(db_path)
    pid = db.create_project("p", str(tmp_path / "out"))
    with pytest.raises(ValueError):
        db.create_pipeline(pid, "car", asset_kind="veh")


def test_migration_adds_import_profile(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE pipelines (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            asset_name TEXT NOT NULL,
            asset_kind TEXT NOT NULL DEFAULT 'character',
            current_stage TEXT NOT NULL DEFAULT 'draft',
            status TEXT NOT NULL DEFAULT 'active',
            selected_concept_provider TEXT,
            selected_concept_asset_id INTEGER,
            rig_provider TEXT NOT NULL DEFAULT 'meshy',
            poly_budget TEXT NOT NULL DEFAULT 'hero',
            multi_view INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()
    init_db(db_path)
    cols = {row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(pipelines)")}
    assert "import_profile" in cols


def test_external_jobs_active_unique_index(tmp_path):
    db_path = tmp_path / "aaa.db"
    db = Database(db_path)
    pid = db.create_project("p", str(tmp_path / "out"))
    plid = db.create_pipeline(pid, "car", asset_kind="vehicle")
    db.save_external_job(plid, "meshy", "task-1", "image-to-3d", status="PENDING")
    db.save_external_job(plid, "meshy", "task-2", "image-to-3d", status="PENDING")
    rows = db.conn.execute(
        "SELECT task_id, status FROM external_jobs WHERE pipeline_id=? AND task_type=?",
        (plid, "image-to-3d"),
    ).fetchall()
    active = [r for r in rows if r["status"] not in ("CANCELED", "FAILED", "SUCCEEDED")]
    assert len(active) == 1


def test_upm_package_has_no_meshy_bridge_refs():
    root = Path(__file__).resolve().parents[1] / "unity_package" / "com.assetassembly.import"
    forbidden = ("ai.meshy", "MeshyBridge")
    for path in root.rglob("*.cs"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} references forbidden token {token}"
