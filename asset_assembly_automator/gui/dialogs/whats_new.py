from __future__ import annotations

import markdown
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

from asset_assembly_automator import __version__
from asset_assembly_automator.core.db.models import Database


class WhatsNewDialog(QDialog):
    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(f"What's New — v{__version__}")
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        md_path = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "resources"
            / "whatsnew"
            / f"{__version__}.md"
        )
        if md_path.exists():
            browser.setHtml(markdown.markdown(md_path.read_text(encoding="utf-8")))
        else:
            browser.setPlainText(f"No release notes for v{__version__}")
        layout.addWidget(browser)
        self.dont_show = QCheckBox("Don't show release notes on update")
        layout.addWidget(self.dont_show)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        if self.dont_show.isChecked():
            self.db.set_setting("show_whats_new", "false")
            QSettings("AssetAssemblyAutomator", "AAA").setValue("show_whats_new", False)
        self.db.set_setting("last_seen_version", __version__)
        super().accept()
