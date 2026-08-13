"""Lightweight workflow template loaders (no stage/client imports)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

UNITY_IMPORT_TEMPLATE_PLACEHOLDERS = (
    "character_slug",
    "unity_project_path",
    "character_dir",
    "unity_import_zip",
    "manifest_path",
    "clips",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def load_unity_import_template() -> str:
    path = _repo_root() / "config" / "workflows" / "unity_import.md"
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_unity_cleanup_template() -> str:
    path = _repo_root() / "config" / "workflows" / "unity_import_cleanup.md"
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_unity_import_repair_template() -> str:
    path = _repo_root() / "config" / "workflows" / "unity_import_repair.md"
    return path.read_text(encoding="utf-8")
