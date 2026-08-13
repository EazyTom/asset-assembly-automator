from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
)

from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.secrets import magnific_api_key, meshy_api_key, set_secret
from asset_assembly_automator.gui.theme.theme import load_theme_pref, save_theme_pref


class SettingsDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Settings")
        form = QFormLayout(self)
        self.meshy_key = QLineEdit()
        self.meshy_key.setEchoMode(QLineEdit.EchoMode.Password)
        if meshy_api_key():
            self.meshy_key.setPlaceholderText("••••••••")

        self.magnific_key = QLineEdit()
        self.magnific_key.setEchoMode(QLineEdit.EchoMode.Password)
        if magnific_api_key():
            self.magnific_key.setPlaceholderText("••••••••")

        self.agent_provider = QComboBox()
        self.agent_provider.addItem("Cursor CLI", "cursor")
        self.agent_provider.addItem("Claude CLI", "claude")
        stored_agent = self.db.get_setting("agent_cli_provider", default="cursor") or "cursor"
        idx = self.agent_provider.findData(stored_agent)
        if idx >= 0:
            self.agent_provider.setCurrentIndex(idx)

        self.unity_mcp_bridge = QComboBox()
        self.unity_mcp_bridge.addItem("AnkleBreaker (default)", "anklebreaker")
        self.unity_mcp_bridge.addItem("Coplay Unity MCP", "coplay")
        self.unity_mcp_bridge.addItem("Official Unity MCP", "official")
        stored_bridge = (
            self.db.get_setting("unity_mcp_bridge", default="anklebreaker") or "anklebreaker"
        )
        bridge_idx = self.unity_mcp_bridge.findData(stored_bridge)
        if bridge_idx >= 0:
            self.unity_mcp_bridge.setCurrentIndex(bridge_idx)

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
        form.addRow("Magnific API key", self.magnific_key)
        form.addRow("Agent for Unity repair", self.agent_provider)
        form.addRow("Unity MCP bridge", self.unity_mcp_bridge)
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
        if self.magnific_key.text().strip():
            set_secret("MAGNIFIC_API_KEY", self.magnific_key.text().strip())
        self.db.set_setting("agent_cli_provider", str(self.agent_provider.currentData()))
        self.db.set_setting("unity_mcp_bridge", str(self.unity_mcp_bridge.currentData()))
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
