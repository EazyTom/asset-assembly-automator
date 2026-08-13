from asset_assembly_automator.workflow.unity_helpers import (
    ensure_unity_import_helpers,
    helpers_present,
)


def test_ensure_unity_import_helpers_installs_upm_package(tmp_path):
    unity_root = tmp_path / "UnityProject"
    (unity_root / "Assets").mkdir(parents=True)

    result = ensure_unity_import_helpers(unity_root)

    assert not result.missing_source
    package_dir = unity_root / "Packages" / "com.assetassembly.import"
    assert package_dir.is_dir()
    assert helpers_present(unity_root)
    assert (package_dir / "Editor" / "CharacterManifestImportUtility.cs").is_file()


def test_ensure_unity_import_helpers_skips_unchanged(tmp_path):
    unity_root = tmp_path / "UnityProject"
    (unity_root / "Assets").mkdir(parents=True)

    first = ensure_unity_import_helpers(unity_root)
    second = ensure_unity_import_helpers(unity_root)

    assert first.installed or first.updated
    assert second.unchanged


def test_ensure_unity_import_helpers_updates_stale_package(tmp_path):
    unity_root = tmp_path / "UnityProject"
    package_dir = unity_root / "Packages" / "com.assetassembly.import"
    stale = package_dir / "package.json"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"name":"stale"}', encoding="utf-8")

    result = ensure_unity_import_helpers(unity_root)

    assert result.updated or result.installed
    assert "com.assetassembly.import" in result.package_path
