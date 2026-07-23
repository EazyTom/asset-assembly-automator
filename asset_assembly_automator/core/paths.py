from __future__ import annotations

import os
import shutil
from pathlib import Path

_LEGACY_DIR_NAMES = ("%LOCALAPPDATA%", "%USERPROFILE%")


def expand_path(value: str | Path) -> Path:
    """Expand Windows env vars (%LOCALAPPDATA%) and ~ in config paths."""
    text = os.path.expandvars(os.path.expanduser(str(value)))
    return Path(text)


def path_needs_expansion(value: str | Path) -> bool:
    text = str(value)
    return any(token in text for token in _LEGACY_DIR_NAMES)


def legacy_app_data_dirs() -> list[Path]:
    """Locations created before path expansion (literal %LOCALAPPDATA% folders)."""
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path.cwd() / "%LOCALAPPDATA%" / "AssetAssemblyAutomator",
        repo_root / "%LOCALAPPDATA%" / "AssetAssemblyAutomator",
    ]
    seen: set[Path] = set()
    result: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.exists():
            result.append(path)
    return result


def migrate_legacy_app_data(target: Path) -> list[str]:
    """Move app data from legacy literal folders into the canonical AppData path."""
    target.mkdir(parents=True, exist_ok=True)
    actions: list[str] = []
    for legacy in legacy_app_data_dirs():
        if legacy.resolve() == target.resolve():
            continue
        for item in legacy.iterdir():
            dest = target / item.name
            if dest.exists():
                if item.is_file() and item.stat().st_size == dest.stat().st_size:
                    item.unlink()
                    actions.append(f"removed duplicate legacy file {item}")
                continue
            shutil.move(str(item), str(dest))
            actions.append(f"moved {item} -> {dest}")
        _remove_legacy_tree_if_empty(legacy)
    return actions


def _remove_legacy_tree_if_empty(path: Path) -> None:
    try:
        if path.exists() and not any(path.iterdir()):
            path.rmdir()
            parent = path.parent
            if parent.name in _LEGACY_DIR_NAMES and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
    except OSError:
        pass
