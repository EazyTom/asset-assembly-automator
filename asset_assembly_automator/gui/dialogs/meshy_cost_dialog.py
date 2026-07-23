from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

STANDARD_IDLE_COUNT = 3


def estimate_meshy_credits(*, idle_anim_count: int = STANDARD_IDLE_COUNT) -> dict[str, int]:
    credits = {
        "image_to_3d": 15,
        "remesh": 5,
        "rig": 5,
        "idle_animations": 3 * idle_anim_count,
    }
    credits["total"] = sum(credits.values())
    return credits


class MeshyCostConfirmDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        asset_name: str,
        idle_anim_count: int = STANDARD_IDLE_COUNT,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm Meshy run")
        layout = QVBoxLayout(self)
        credits = estimate_meshy_credits(idle_anim_count=idle_anim_count)
        lines = [
            f"Run Meshy pipeline for {asset_name}?",
            "",
            "Estimated Meshy credits:",
            f"- Image-to-3D: ~{credits['image_to_3d']}",
            f"- Remesh: {credits['remesh']}",
            f"- Rig (walk/run included): {credits['rig']}",
            (
                f"- Idle animations ({idle_anim_count} × 3): {credits['idle_animations']}"
                f" — idle3, idle4, idle12"
            ),
            "",
            f"Estimated total: ~{credits['total']} credits",
        ]
        body = QLabel("\n".join(lines))
        body.setWordWrap(True)
        layout.addWidget(body)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
