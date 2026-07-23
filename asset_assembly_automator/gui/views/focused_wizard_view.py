from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget

from asset_assembly_automator.core.state_machine import CHARACTER_STAGE_ORDER


class FocusedWizardView(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Pipeline Steps"))
        self.steps = QListWidget()
        for stage in CHARACTER_STAGE_ORDER:
            self.steps.addItem(stage.value)
        layout.addWidget(self.steps)
        self.detail = QLabel("Select a pipeline from the dashboard to focus.")
        layout.addWidget(self.detail)

    def set_pipeline(self, asset_name: str, current_stage: str) -> None:
        self.detail.setText(f"Focused: {asset_name} — current stage: {current_stage}")
        for i in range(self.steps.count()):
            item = self.steps.item(i)
            if item.text() == current_stage:
                self.steps.setCurrentRow(i)
                break
