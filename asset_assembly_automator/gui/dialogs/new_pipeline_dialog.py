from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSlider,
)

from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import Database


class NewPipelineDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("New Pipeline")
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
        self.asset_kind = QComboBox()
        self.asset_kind.addItem("Character", "character")
        self.asset_kind.addItem("Vehicle", "vehicle")
        self.asset_kind.addItem("Aircraft", "aircraft")

        self.meshy_preset = QComboBox()
        self.meshy_preset.addItem("Quality (meshy-7, 8K)", "quality")
        self.meshy_preset.addItem("Game-ready (smart-topology)", "game_ready")

        self.texture_resolution = QComboBox()
        self.texture_resolution.addItems(["2k", "4k", "8k"])
        self.texture_resolution.setCurrentText(settings.meshy.default_texture_resolution)

        self.image_enhancement = QCheckBox("Image enhancement")
        self.image_enhancement.setChecked(settings.meshy.image_enhancement)

        self.remesh_enabled = QCheckBox("Run remesh (Quality only)")
        self.remesh_enabled.setChecked(False)

        self.magnific_enabled = QCheckBox("Auto Magnific uprez after concept approval")
        self.magnific_enabled.setChecked(settings.magnific.default_enabled)

        self.poly_slider = QSlider(Qt.Orientation.Horizontal)
        self.poly_slider.setRange(100, 15000)
        self.poly_slider.setValue(4000)
        self.poly_label = QLabel("4000")
        self.poly_slider.valueChanged.connect(lambda v: self.poly_label.setText(str(v)))
        poly_row = QHBoxLayout()
        poly_row.addWidget(self.poly_slider)
        poly_row.addWidget(self.poly_label)

        self.poly_budget = QComboBox()
        self.poly_budget.addItems(["hero", "npc", "crowd"])
        self.poly_budget.setCurrentText("hero")

        if self._has_projects:
            form.addRow("Project", self.project_combo)
        else:
            form.addRow("New project name", self.project_name)
            form.addRow("Output folder", self.output_root)

        form.addRow("Asset type", self.asset_kind)
        form.addRow("Asset name", self.asset_name)
        form.addRow("Meshy preset", self.meshy_preset)
        form.addRow("Texture resolution", self.texture_resolution)
        form.addRow(self.image_enhancement)
        form.addRow(self.remesh_enabled)
        form.addRow(self.magnific_enabled)
        form.addRow("Game-ready polycount", poly_row)
        form.addRow("Poly budget", self.poly_budget)

        self.meshy_preset.currentIndexChanged.connect(self._sync_preset_ui)
        self._sync_preset_ui()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.pipeline_id: int | None = None

    def _sync_preset_ui(self) -> None:
        game_ready = self.meshy_preset.currentData() == "game_ready"
        self.texture_resolution.setEnabled(not game_ready)
        self.remesh_enabled.setEnabled(not game_ready)
        self.poly_slider.setEnabled(game_ready)

    def accept(self) -> None:
        asset_name = self.asset_name.text().strip()
        if not asset_name:
            QMessageBox.warning(self, "Missing name", "Enter an asset name.")
            return

        project_id = self._resolve_project_id()
        if project_id is None:
            QMessageBox.warning(
                self,
                "Missing project",
                "Select a project or enter a project name and output folder.",
            )
            return

        metadata = {
            "meshy_preset": self.meshy_preset.currentData(),
            "texture_resolution": self.texture_resolution.currentText(),
            "image_enhancement": self.image_enhancement.isChecked(),
            "remesh_enabled": self.remesh_enabled.isChecked(),
            "magnific_enabled": self.magnific_enabled.isChecked(),
            "smart_topology_polycount": self.poly_slider.value(),
        }
        self.pipeline_id = self.db.create_pipeline(
            project_id,
            asset_name,
            poly_budget=self.poly_budget.currentText(),
            asset_kind=str(self.asset_kind.currentData()),
            metadata=metadata,
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
