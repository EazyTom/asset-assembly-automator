from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget

from asset_assembly_automator.core.state_machine import StageId

PHASE2_STAGES = [
    (StageId.WORLD_CONCEPT, "World concept generation"),
    (StageId.WORLD_I2D, "World Meshy image-to-3D"),
    (StageId.WORLD_REMESH, "World remesh + LOD"),
    (StageId.WORLD_EXPORT, "World export bundle"),
]


class Phase2StubView(QWidget):
    """Reserved world stages. Unity import already runs from the workflow window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        note = QLabel(
            "World stages are reserved and not runnable. "
            "Character, vehicle, and aircraft pipelines already export FBX.zip "
            "and can import into Unity from the workflow window."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.list = QListWidget()
        for stage, label in PHASE2_STAGES:
            self.list.addItem(f"{stage.value} — {label}")
        layout.addWidget(self.list)
