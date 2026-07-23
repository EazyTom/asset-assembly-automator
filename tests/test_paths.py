from __future__ import annotations

import os
from pathlib import Path

from asset_assembly_automator.core.config import load_settings
from asset_assembly_automator.core.paths import expand_path, migrate_legacy_app_data


def test_expand_path_expands_localappdata():
    path = expand_path("%LOCALAPPDATA%/AssetAssemblyAutomator")
    assert "%LOCALAPPDATA%" not in str(path)
    assert path == Path(os.environ["LOCALAPPDATA"]) / "AssetAssemblyAutomator"


def test_load_settings_expands_yaml_paths():
    settings = load_settings()
    assert "%LOCALAPPDATA%" not in str(settings.paths.app_data)
    assert settings.paths.app_data.is_absolute()


def test_migrate_legacy_app_data(tmp_path, monkeypatch):
    legacy = tmp_path / "repo" / "%LOCALAPPDATA%" / "AssetAssemblyAutomator"
    legacy.mkdir(parents=True)
    (legacy / "aaa.db").write_text("legacy-db", encoding="utf-8")

    target = tmp_path / "canonical"
    monkeypatch.chdir(tmp_path / "repo")
    actions = migrate_legacy_app_data(target)

    assert actions
    assert (target / "aaa.db").read_text(encoding="utf-8") == "legacy-db"
    assert not legacy.exists()
