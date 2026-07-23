from __future__ import annotations

import markdown
from PyQt6.QtCore import QSettings, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.secrets import meshy_api_key


class GettingStartedDialog(QDialog):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Getting Started — Asset Assembly Automator")
        self.resize(640, 520)

        layout = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        md_path = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "resources"
            / "onboarding"
            / "getting_started.md"
        )
        if md_path.exists():
            html = markdown.markdown(md_path.read_text(encoding="utf-8"))
            self.browser.setHtml(html)

        layout.addWidget(self.browser)
        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        self._refresh_status()

        btn_row = QHBoxLayout()
        for label, url in [
            ("Meshy API", "https://www.meshy.ai/settings/api"),
            ("Meshy Rigging Docs", "https://docs.meshy.ai/en/api/rigging-and-animation"),
        ]:
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.dont_show = QCheckBox("Don't show this again")
        layout.addWidget(self.dont_show)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close | QDialogButtonBox.StandardButton.Retry
        )
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Retry).clicked.connect(self._refresh_status)
        layout.addWidget(buttons)

    def _refresh_status(self) -> None:
        key_ok = bool(meshy_api_key())
        self.status_label.setText(
            f"Meshy API key: {'configured' if key_ok else 'missing'} | "
            "Higgsfield MCP: check Cursor plugin | Unity MCP: optional"
        )

    def accept(self) -> None:
        if self.dont_show.isChecked():
            self.db.set_setting("show_getting_started", "false")
            QSettings("AssetAssemblyAutomator", "AAA").setValue("show_getting_started", False)
        super().accept()
