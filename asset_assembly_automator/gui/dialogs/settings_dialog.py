from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
)

from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.secrets import meshy_api_key, set_secret
from asset_assembly_automator.gui.theme.theme import load_theme_pref, save_theme_pref


class SettingsDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Settings")
        form = QFormLayout(self)
        self.meshy_key = QLineEdit()
        self.meshy_key.setEchoMode(QLineEdit.EchoMode.Password)
        existing = meshy_api_key()
        if existing:
            self.meshy_key.setPlaceholderText("••••••••")
        self.mj_watch = QLineEdit(self.db.get_setting("mj_watch_folder", default="") or "")
        self.theme_dark = QCheckBox("Dark theme")
        self.theme_dark.setChecked(load_theme_pref() == "dark")
        self.show_getting_started = QCheckBox("Show Getting Started on startup")
        self.show_getting_started.setChecked(
            self.db.get_setting("show_getting_started", default="true") != "false"
        )
        self.show_whats_new = QCheckBox("Show What's New on update")
        self.show_whats_new.setChecked(
            self.db.get_setting("show_whats_new", default="true") != "false"
        )
        form.addRow("Meshy API key", self.meshy_key)
        form.addRow("MJ watch folder", self.mj_watch)
        form.addRow(self.theme_dark)
        form.addRow(self.show_getting_started)
        form.addRow(self.show_whats_new)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        if self.meshy_key.text().strip():
            set_secret("MESHY_API_KEY", self.meshy_key.text().strip())
        self.db.set_setting("mj_watch_folder", self.mj_watch.text().strip())
        self.db.set_setting(
            "show_getting_started", "true" if self.show_getting_started.isChecked() else "false"
        )
        self.db.set_setting(
            "show_whats_new", "true" if self.show_whats_new.isChecked() else "false"
        )
        save_theme_pref("dark" if self.theme_dark.isChecked() else "light")
        QMessageBox.information(self, "Settings", "Saved. Restart app for theme changes.")
        self.accept()
