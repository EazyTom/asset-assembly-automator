from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from asset_assembly_automator.core.state_machine import (
    CHARACTER_STAGE_ORDER,
    MESHY_WORKFLOW_STAGE_ORDER,
    StageId,
)
from asset_assembly_automator.gui.theme.theme import STATUS_COLORS

_STYLE_COMPLETE = f"color: {STATUS_COLORS['done']}; font-size: 16px; font-weight: bold;"
_STYLE_CURRENT = f"color: {STATUS_COLORS['paused']}; font-size: 16px; font-weight: bold;"
_STYLE_PENDING = f"color: {STATUS_COLORS['queued']}; font-size: 16px;"
_STYLE_STALE = f"color: {STATUS_COLORS['failed']}; font-size: 16px; font-weight: bold;"

STAGE_DISPLAY_LABELS: dict[str, str] = {
    StageId.IMAGE_PREP.value: "Concept Image",
    StageId.MAGNIFIC_UPREZ.value: "Magnific Uprez",
}


def stage_display_label(stage: StageId | str) -> str:
    value = stage.value if isinstance(stage, StageId) else str(stage)
    return STAGE_DISPLAY_LABELS.get(value, value.replace("_", " "))


class PipelineStepper(QWidget):
    def __init__(
        self,
        parent=None,
        *,
        stages: list[StageId] | None = None,
    ) -> None:
        super().__init__(parent)
        self._order = list(stages or self._default_stages())
        self.layout = QHBoxLayout(self)
        self.layout.setSpacing(6)
        self.labels: list[QLabel] = []
        for stage in self._order:
            lbl = QLabel("○")
            lbl.setToolTip(stage_display_label(stage))
            lbl.setStyleSheet(_STYLE_PENDING)
            self.layout.addWidget(lbl)
            self.labels.append(lbl)

    @staticmethod
    def _default_stages() -> list[StageId]:
        return [s for s in CHARACTER_STAGE_ORDER if s != StageId.TURNAROUND]

    def _index_for(self, stage_value: str) -> int | None:
        try:
            return next(i for i, stage in enumerate(self._order) if stage.value == stage_value)
        except StopIteration:
            return None

    def set_stage(self, current: str, *, rerun_from: str | None = None) -> None:
        if rerun_from is not None:
            self._set_stage_with_rerun(current, rerun_from)
            return

        if current == StageId.COMPLETE.value:
            for lbl in self.labels:
                lbl.setText("✓")
                lbl.setStyleSheet(_STYLE_COMPLETE)
            return

        idx = self._index_for(current)
        if idx is None:
            return

        for i, lbl in enumerate(self.labels):
            stage = self._order[i]
            lbl.setToolTip(stage_display_label(stage))
            if i < idx:
                lbl.setText("✓")
                lbl.setStyleSheet(_STYLE_COMPLETE)
            elif i == idx:
                lbl.setText("■")
                lbl.setStyleSheet(_STYLE_CURRENT)
            else:
                lbl.setText("○")
                lbl.setStyleSheet(_STYLE_PENDING)

    def _set_stage_with_rerun(self, current: str, rerun_from: str) -> None:
        rerun_idx = self._index_for(rerun_from)
        if rerun_idx is None:
            self.set_stage(current)
            return

        if current == StageId.COMPLETE.value:
            current_idx = len(self._order) - 1
        else:
            current_idx = self._index_for(current)
            if current_idx is None:
                current_idx = rerun_idx

        for i, lbl in enumerate(self.labels):
            stage = self._order[i]
            name = stage_display_label(stage)
            if i < rerun_idx:
                lbl.setText("✓")
                lbl.setStyleSheet(_STYLE_COMPLETE)
                lbl.setToolTip(name)
            elif i == rerun_idx:
                lbl.setText("■")
                lbl.setStyleSheet(_STYLE_CURRENT)
                lbl.setToolTip(f"{name} — re-run required (assets missing on disk)")
            elif rerun_idx < i <= current_idx:
                lbl.setText("!")
                lbl.setStyleSheet(_STYLE_STALE)
                lbl.setToolTip(f"{name} — stale (files missing; re-run Meshy)")
            else:
                lbl.setText("○")
                lbl.setStyleSheet(_STYLE_PENDING)
                lbl.setToolTip(name)


class MeshyWorkflowStepper(PipelineStepper):
    """Meshy drop workflow: image prep through Unity MCP import."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent, stages=MESHY_WORKFLOW_STAGE_ORDER)

    def set_stage(
        self,
        current: str,
        *,
        rerun_from: str | None = None,
        unity_import_done: bool = False,
        unity_import_failed: bool = False,
    ) -> None:
        unity_idx = self._index_for(StageId.UNITY_IMPORT.value)

        if unity_import_done:
            for lbl in self.labels:
                lbl.setText("✓")
                lbl.setStyleSheet(_STYLE_COMPLETE)
            return

        if rerun_from is not None:
            super().set_stage(current, rerun_from=rerun_from)
            if unity_idx is not None:
                lbl = self.labels[unity_idx]
                lbl.setText("○")
                lbl.setStyleSheet(_STYLE_PENDING)
                lbl.setToolTip("unity import — pending")
            return

        if current == StageId.COMPLETE.value:
            self._set_meshy_complete_unity_pending()
            return

        if current == StageId.UNITY_IMPORT.value:
            self._set_unity_import_step(
                failed=unity_import_failed,
                in_progress=not unity_import_failed,
            )
            return

        super().set_stage(current)
        if unity_idx is not None:
            lbl = self.labels[unity_idx]
            lbl.setText("○")
            lbl.setStyleSheet(_STYLE_PENDING)
            lbl.setToolTip("unity import — pending")

    def _set_meshy_complete_unity_pending(self) -> None:
        unity_idx = self._index_for(StageId.UNITY_IMPORT.value)
        last_meshy_idx = (
            self._index_for(StageId.PACKAGE_EXPORT.value)
            if self._index_for(StageId.PACKAGE_EXPORT.value) is not None
            else len(self._order) - 2
        )
        for i, lbl in enumerate(self.labels):
            stage = self._order[i]
            name = stage_display_label(stage)
            if unity_idx is not None and i == unity_idx:
                lbl.setText("○")
                lbl.setStyleSheet(_STYLE_PENDING)
                lbl.setToolTip(f"{name} — pending")
            elif i <= last_meshy_idx:
                lbl.setText("✓")
                lbl.setStyleSheet(_STYLE_COMPLETE)
                lbl.setToolTip(name)
            else:
                lbl.setText("○")
                lbl.setStyleSheet(_STYLE_PENDING)
                lbl.setToolTip(name)

    def _set_unity_import_step(self, *, failed: bool, in_progress: bool) -> None:
        unity_idx = self._index_for(StageId.UNITY_IMPORT.value)
        if unity_idx is None:
            return
        for i, lbl in enumerate(self.labels):
            stage = self._order[i]
            name = stage_display_label(stage)
            if i < unity_idx:
                lbl.setText("✓")
                lbl.setStyleSheet(_STYLE_COMPLETE)
                lbl.setToolTip(name)
            elif i == unity_idx:
                if failed:
                    lbl.setText("!")
                    lbl.setStyleSheet(_STYLE_STALE)
                    lbl.setToolTip(f"{name} — failed (retry import)")
                elif in_progress:
                    lbl.setText("■")
                    lbl.setStyleSheet(_STYLE_CURRENT)
                    lbl.setToolTip(f"{name} — in progress")
                else:
                    lbl.setText("○")
                    lbl.setStyleSheet(_STYLE_PENDING)
                    lbl.setToolTip(f"{name} — pending")
            else:
                lbl.setText("○")
                lbl.setStyleSheet(_STYLE_PENDING)
                lbl.setToolTip(name)
