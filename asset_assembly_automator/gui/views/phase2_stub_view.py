from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget

from asset_assembly_automator.core.state_machine import StageId

PHASE2_STAGES = [
    (StageId.WORLD_CONCEPT, "World concept generation (Phase 2)"),
    (StageId.WORLD_I2D, "World Meshy image-to-3D (Phase 2)"),
    (StageId.WORLD_REMESH, "World remesh + LOD (Phase 2)"),
    (StageId.WORLD_EXPORT, "World export bundle (Phase 2)"),
    (StageId.UNITY_IMPORT, "Unity MCP URP Humanoid import (Phase 2)"),
]


class Phase2StubView(QWidget):
    """Reserved slots for worldbuilding + Unity import — not wired to runner in v1."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Phase 2 pipelines are schema-ready but not executable in v1. "
                "Character pipelines export FBX.zip for manual Unity import."
            )
        )
        self.list = QListWidget()
        for stage, label in PHASE2_STAGES:
            self.list.addItem(f"{stage.value} — {label}")
        layout.addWidget(self.list)
