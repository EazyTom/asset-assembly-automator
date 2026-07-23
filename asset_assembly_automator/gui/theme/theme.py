from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

STATUS_COLORS = {
    "running": "#3B82F6",
    "done": "#22C55E",
    "failed": "#EF4444",
    "paused": "#EAB308",
    "queued": "#94A3B8",
}

LOG_LEVEL_COLORS = {
    "debug": "#94A3B8",
    "info": "#3B82F6",
    "warning": "#EAB308",
    "error": "#EF4444",
}


def setup_theme(app: QApplication, theme: str = "dark") -> None:
    try:
        import qdarktheme

        qdarktheme.setup_theme(theme)
    except ImportError:
        pass
    qss_path = Path(__file__).resolve().parent / "dark.qss"
    if qss_path.exists():
        app.setStyleSheet(app.styleSheet() + qss_path.read_text(encoding="utf-8"))


def save_theme_pref(theme: str) -> None:
    settings = QSettings("AssetAssemblyAutomator", "AAA")
    settings.setValue("theme", theme)


def load_theme_pref(default: str = "dark") -> str:
    settings = QSettings("AssetAssemblyAutomator", "AAA")
    return settings.value("theme", default, type=str)
