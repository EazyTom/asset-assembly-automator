from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
)

from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import Database


class NewPipelineDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("New Character Pipeline")
        form = QFormLayout(self)
        self.project_combo = QComboBox()
        rows = self.db.conn.execute("SELECT id, name FROM projects ORDER BY id DESC").fetchall()
        self._has_projects = bool(rows)
        for r in rows:
            self.project_combo.addItem(r["name"], r["id"])

        self.project_name = QLineEdit("Default Project")
        settings = get_settings()
        self.output_root = QLineEdit(str(settings.paths.app_data / "Output"))

        self.asset_name = QLineEdit()
        self.poly_budget = QComboBox()
        self.poly_budget.addItems(["hero", "npc", "crowd"])
        self.poly_budget.setCurrentText("hero")
        self.pipeline_type = QComboBox()
        self.pipeline_type.addItem("Character (v1)", "character")
        self.pipeline_type.addItem("Worldbuilding (Phase 2 — stub)", "world")

        if self._has_projects:
            form.addRow("Project", self.project_combo)
        else:
            form.addRow("New project name", self.project_name)
            form.addRow("Output folder", self.output_root)

        form.addRow("Pipeline type", self.pipeline_type)
        form.addRow("Asset name", self.asset_name)
        form.addRow("Poly budget", self.poly_budget)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.pipeline_id: int | None = None

    def accept(self) -> None:
        asset_name = self.asset_name.text().strip()
        if not asset_name:
            QMessageBox.warning(self, "Missing name", "Enter an asset name.")
            return
        if self.pipeline_type.currentData() == "world":
            QMessageBox.information(
                self,
                "Phase 2",
                "Worldbuilding pipelines are reserved in the schema but not runnable in v1.",
            )
            return

        project_id = self._resolve_project_id()
        if project_id is None:
            QMessageBox.warning(
                self,
                "Missing project",
                "Select a project or enter a project name and output folder.",
            )
            return

        self.pipeline_id = self.db.create_pipeline(
            project_id,
            asset_name,
            poly_budget=self.poly_budget.currentText(),
        )
        super().accept()

    def _resolve_project_id(self) -> int | None:
        if self._has_projects:
            raw = self.project_combo.currentData()
            if raw is not None:
                return int(raw)

        name = self.project_name.text().strip()
        output_root = self.output_root.text().strip()
        if not name or not output_root:
            settings = get_settings()
            if not self._has_projects:
                return None
            name = name or "Default Project"
            output_root = output_root or str(settings.paths.app_data / "Output")

        return self.db.create_project(name, output_root)
