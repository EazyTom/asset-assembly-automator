from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from asset_assembly_automator.core.state_machine import StageId, stage_progress
from asset_assembly_automator.gui.theme.theme import STATUS_COLORS


class DashboardView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.grid = QGridLayout(self)
        self._cards: dict[int, QFrame] = {}

    def refresh(self, pipelines) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._cards.clear()
        for i, pipe in enumerate(pipelines):
            card = QFrame()
            card.setObjectName("DashboardCard")
            lay = QVBoxLayout(card)
            title = QLabel(pipe.asset_name)
            title.setStyleSheet("font-weight: bold; font-size: 14px;")
            stage = QLabel(pipe.current_stage)
            pct = stage_progress(StageId(pipe.current_stage))
            bar = QLabel("█" * (pct // 10) + "░" * (10 - pct // 10))
            status = QLabel(pipe.status)
            color = STATUS_COLORS.get("done" if pipe.status == "complete" else "running", "#94A3B8")
            status.setStyleSheet(f"color: {color};")
            lay.addWidget(title)
            lay.addWidget(stage)
            lay.addWidget(bar)
            lay.addWidget(status)
            self.grid.addWidget(card, i // 3, i % 3)
            self._cards[pipe.id] = card
