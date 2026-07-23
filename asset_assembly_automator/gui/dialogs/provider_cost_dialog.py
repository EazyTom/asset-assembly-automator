from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


def estimate_magnific_mystic_cost(*, resolution: str = "2k") -> str:
    estimates = {"1k": "~€0.10", "2k": "~€0.20", "4k": "~€0.40"}
    return estimates.get(resolution.lower(), "~€0.20")


def estimate_magnific_upscale_cost(*, scale_factor: str, mode: str) -> str:
    scale = scale_factor.strip().lower().rstrip("x")
    try:
        factor = int(scale)
    except ValueError:
        factor = 2
    base = 0.10
    multiplier = {2: 1.0, 4: 2.0, 8: 5.0, 16: 10.0}.get(factor, factor / 2.0)
    euros = round(base * multiplier, 2)
    mode_label = "Creative" if mode == "creative" else "Precision V2"
    return f"~€{euros:.2f} ({mode_label}, {factor}x)"


def estimate_higgsfield_generate_cost() -> str:
    return "~1 Higgsfield credit"


class ProviderCostConfirmDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        title: str,
        action: str,
        asset_name: str,
        cost_line: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        lines = [
            f"{action} for {asset_name}?",
            "",
            f"Estimated cost: {cost_line}",
            "",
            "Credits will be charged to your provider account.",
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
