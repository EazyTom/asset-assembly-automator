from pathlib import Path

from asset_assembly_automator.workflow.unity_helpers import (
    ensure_unity_import_helpers,
    helpers_present,
)


def test_ensure_unity_import_helpers_installs_on_fresh_project(tmp_path):
    unity_root = tmp_path / "UnityProject"
    (unity_root / "Assets").mkdir(parents=True)

    result = ensure_unity_import_helpers(unity_root)

    assert not result.missing_templates
    assert len(result.installed) == 2
    assert helpers_present(unity_root)
    assert (unity_root / "Assets/Editor/CharacterManifestImportUtility.cs").is_file()
    assert (unity_root / "Assets/Scripts/CharacterOvalPatrol.cs").is_file()


def test_ensure_unity_import_helpers_skips_unchanged(tmp_path):
    unity_root = tmp_path / "UnityProject"
    (unity_root / "Assets").mkdir(parents=True)

    first = ensure_unity_import_helpers(unity_root)
    second = ensure_unity_import_helpers(unity_root)

    assert len(first.installed) == 2
    assert not second.installed
    assert not second.updated
    assert len(second.unchanged) == 2


def test_ensure_unity_import_helpers_updates_stale_copy(tmp_path):
    unity_root = tmp_path / "UnityProject"
    editor_dir = unity_root / "Assets/Editor"
    editor_dir.mkdir(parents=True)
    stale = editor_dir / "CharacterManifestImportUtility.cs"
    stale.write_text("// stale", encoding="utf-8")

    result = ensure_unity_import_helpers(unity_root)

    assert stale.name in Path(result.updated[0]).name or any(
        "CharacterManifestImportUtility" in path for path in result.updated
    )
    assert "// stale" not in stale.read_text(encoding="utf-8")
