"""Install com.assetassembly.import UPM package into a Unity project."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PACKAGE_SOURCE = _REPO_ROOT / "unity_package" / "com.assetassembly.import"
_PACKAGE_NAME = "com.assetassembly.import"
_FALLBACK_TEMPLATES = _REPO_ROOT / "unity_templates" / "Assets"


@dataclass
class UnityPackageInstallResult:
    installed: bool = False
    updated: bool = False
    unchanged: bool = False
    used_fallback: bool = False
    package_path: str = ""
    missing_source: bool = False
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.missing_source:
            return "package source missing"
        parts: list[str] = []
        if self.installed:
            parts.append("installed")
        if self.updated:
            parts.append("updated")
        if self.unchanged:
            parts.append("unchanged")
        if self.used_fallback:
            parts.append("fallback Assets copy")
        return ", ".join(parts) if parts else "no changes"


def _digest_dir(path: Path) -> str:
    h = hashlib.sha256()
    for file in sorted(path.rglob("*")):
        if file.is_file() and file.suffix not in {".meta"}:
            rel = file.relative_to(path).as_posix()
            h.update(rel.encode())
            h.update(file.read_bytes())
    return h.hexdigest()


def ensure_unity_import_package(unity_project_path: Path | str) -> UnityPackageInstallResult:
    """Sync AAA UPM package into Unity Packages/com.assetassembly.import."""
    unity_root = Path(unity_project_path)
    dest = unity_root / "Packages" / _PACKAGE_NAME
    result = UnityPackageInstallResult(package_path=str(dest))

    if not _PACKAGE_SOURCE.is_dir():
        result.missing_source = True
        return _fallback_copy_helpers(unity_root, result)

    source_digest = _digest_dir(_PACKAGE_SOURCE)
    if dest.is_dir():
        dest_digest = _digest_dir(dest)
        if dest_digest == source_digest:
            result.unchanged = True
            return result
        shutil.rmtree(dest)
        result.updated = True
    else:
        result.installed = True

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(_PACKAGE_SOURCE, dest)
    return result


def _fallback_copy_helpers(
    unity_root: Path, result: UnityPackageInstallResult
) -> UnityPackageInstallResult:
    """Last resort: copy legacy template scripts into Assets/AAA.Import/."""
    result.used_fallback = True
    for rel_template, rel_dest in HELPER_FILES.items():
        src = _FALLBACK_TEMPLATES / rel_template
        dest = unity_root / rel_dest.replace("Assets/", "Assets/AAA.Import/")
        if not src.is_file():
            result.errors.append(f"missing template {src}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return result


HELPER_FILES: dict[str, str] = {
    "Editor/CharacterManifestImportUtility.cs": "Assets/Editor/CharacterManifestImportUtility.cs",
    "Scripts/CharacterOvalPatrol.cs": "Assets/Scripts/CharacterOvalPatrol.cs",
}


def ensure_unity_import_helpers(unity_project_path: Path | str) -> UnityPackageInstallResult:
    """Backward-compatible alias — installs UPM package (preferred) or fallback Assets copy."""
    return ensure_unity_import_package(unity_project_path)


def helpers_present(unity_project_path: Path | str) -> bool:
    unity_root = Path(unity_project_path)
    package_editor = (
        unity_root / "Packages" / _PACKAGE_NAME / "Editor" / "CharacterManifestImportUtility.cs"
    )
    if package_editor.is_file():
        return True
    legacy = unity_root / "Assets" / "Editor" / "CharacterManifestImportUtility.cs"
    return legacy.is_file()


def unity_asset_root(unity_project_path: Path | str, asset_kind: str, slug: str) -> Path:
    folder = {"character": "Characters", "vehicle": "Vehicles", "aircraft": "Aircraft"}.get(
        asset_kind, "Characters"
    )
    return Path(unity_project_path) / "Assets" / folder / slug
