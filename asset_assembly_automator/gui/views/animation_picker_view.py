from __future__ import annotations

import qasync
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget

from asset_assembly_automator.clients.animation_catalog import AnimationCatalog


class AnimationPickerView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Meshy animation library"))
        search_row = QHBoxLayout()
        self.search_btn = QPushButton("Load defaults + search 'casual walk'")
        search_row.addWidget(self.search_btn)
        layout.addLayout(search_row)
        self.list = QListWidget()
        layout.addWidget(self.list)
        self.search_btn.clicked.connect(self._load)

    @qasync.asyncSlot()
    async def _load(self) -> None:
        catalog = AnimationCatalog()
        await catalog.sync(force=True)
        defaults = catalog.resolve_defaults()
        results = catalog.search("casual walk", limit=5)
        self.list.clear()
        for item in defaults + results:
            name = item.get("action_name", "?")
            aid = item.get("action_id", "?")
            self.list.addItem(f"{name} (id={aid})")
