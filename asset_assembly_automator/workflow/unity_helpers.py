"""Install AAA Unity import helper scripts into a Unity project."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# workflow/ -> asset_assembly_automator/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATES_ROOT = _REPO_ROOT / "unity_templates" / "Assets"

HELPER_FILES: dict[str, str] = {
    "Editor/CharacterManifestImportUtility.cs": "Assets/Editor/CharacterManifestImportUtility.cs",
    "Scripts/CharacterOvalPatrol.cs": "Assets/Scripts/CharacterOvalPatrol.cs",
}


@dataclass
class UnityHelperInstallResult:
    installed: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    missing_templates: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.installed or self.updated)

    def summary(self) -> str:
        parts: list[str] = []
        if self.installed:
            parts.append(f"installed {len(self.installed)}")
        if self.updated:
            parts.append(f"updated {len(self.updated)}")
        if self.unchanged:
            parts.append(f"unchanged {len(self.unchanged)}")
        if self.missing_templates:
            parts.append(f"missing templates {len(self.missing_templates)}")
        return ", ".join(parts) if parts else "no helper scripts configured"


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_unity_import_helpers(unity_project_path: Path | str) -> UnityHelperInstallResult:
    """Copy helper C# scripts from unity_templates into the Unity project if missing or stale."""
    unity_root = Path(unity_project_path)
    assets_root = unity_root / "Assets"
    result = UnityHelperInstallResult()

    assets_root.mkdir(parents=True, exist_ok=True)

    for rel_template, rel_dest in HELPER_FILES.items():
        src = _TEMPLATES_ROOT / rel_template
        dest = unity_root / rel_dest

        if not src.is_file():
            result.missing_templates.append(str(src))
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)

        if not dest.exists():
            shutil.copy2(src, dest)
            result.installed.append(str(dest))
            continue

        if _file_digest(src) == _file_digest(dest):
            result.unchanged.append(str(dest))
            continue

        shutil.copy2(src, dest)
        result.updated.append(str(dest))

    return result


def helper_script_paths(unity_project_path: Path | str) -> dict[str, Path]:
    """Return expected helper script paths inside a Unity project."""
    unity_root = Path(unity_project_path)
    return {name: unity_root / dest for name, dest in HELPER_FILES.items()}


def helpers_present(unity_project_path: Path | str) -> bool:
    """True when both helper scripts exist in the Unity project."""
    paths = helper_script_paths(unity_project_path)
    return all(path.is_file() for path in paths.values())
