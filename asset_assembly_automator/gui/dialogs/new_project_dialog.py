from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import Database


class NewProjectDialog(QDialog):
    def __init__(self, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.db = db
        self.project_id: int | None = None
        self.setWindowTitle("New Project")

        form = QFormLayout(self)
        self.project_name = QLineEdit()
        settings = get_settings()
        self.output_root = QLineEdit(str(settings.paths.app_data / "Output"))

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_root)
        output_browse = QPushButton("Browse…")
        output_browse.clicked.connect(self._browse_output)
        output_row.addWidget(output_browse)

        self.unity_path = QLineEdit()
        self.unity_path.setPlaceholderText("Optional — Unity project root")
        unity_row = QHBoxLayout()
        unity_row.addWidget(self.unity_path)
        unity_browse = QPushButton("Browse…")
        unity_browse.clicked.connect(self._browse_unity)
        unity_row.addWidget(unity_browse)

        form.addRow("Project name", self.project_name)
        form.addRow("Output folder", output_row)
        form.addRow("Unity project", unity_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select character output folder")
        if path:
            self.output_root.setText(path)

    def _browse_unity(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Unity project folder")
        if path:
            self.unity_path.setText(path)

    def _accept(self) -> None:
        name = self.project_name.text().strip()
        output_root = self.output_root.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Enter a project name.")
            return
        if not output_root:
            QMessageBox.warning(self, "Missing folder", "Enter an output folder.")
            return
        unity = self.unity_path.text().strip() or None
        self.project_id = self.db.create_project(name, output_root, unity_project_path=unity)
        self.accept()
