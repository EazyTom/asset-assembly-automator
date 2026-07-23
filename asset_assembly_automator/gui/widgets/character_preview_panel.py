from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QScrollArea, QSplitter, QVBoxLayout, QWidget

from asset_assembly_automator.gui.widgets.drop_zone import DropZone
from asset_assembly_automator.gui.widgets.zoom_preview_label import (
    ZoomPreviewLabel,
    configure_zoom_scroll_area,
)


class CharacterPreviewPanel(QWidget):
    """Side-by-side T-pose input and pre-rig Meshy mesh preview."""

    filesDropped = pyqtSignal(list)

    _MESH_PLACEHOLDER = (
        "Run Meshy to generate mesh preview\n\nPreview from Meshy texturing (pre-rig)"
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.drop_zone = DropZone()
        self.drop_zone.filesDropped.connect(self.filesDropped.emit)
        splitter.addWidget(self.drop_zone)

        mesh_panel = QWidget()
        mesh_layout = QVBoxLayout(mesh_panel)
        mesh_layout.setContentsMargins(8, 0, 0, 0)
        self.mesh_hint = QLabel(self._MESH_PLACEHOLDER)
        self.mesh_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mesh_hint.setWordWrap(True)
        self.mesh_scroll = QScrollArea()
        self.mesh_scroll.setMinimumHeight(200)
        self.mesh_preview = ZoomPreviewLabel()
        self.mesh_preview.setMinimumSize(240, 180)
        configure_zoom_scroll_area(self.mesh_scroll, self.mesh_preview)
        mesh_layout.addWidget(self.mesh_hint)
        mesh_layout.addWidget(self.mesh_scroll, stretch=1)
        splitter.addWidget(mesh_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)
        self._show_mesh_placeholder()

    def show_tpose_preview(self, path: str) -> None:
        self.drop_zone._show_preview(path)  # noqa: SLF001

    def clear_tpose_preview(self) -> None:
        self.drop_zone.clear_preview()

    def show_mesh_preview(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._show_mesh_placeholder("Could not load mesh preview image.")
            return
        self.mesh_hint.hide()
        self.mesh_preview.set_source_pixmap(pixmap)

    def clear_mesh_preview(self, *, show_placeholder: bool = True) -> None:
        self.mesh_preview.set_source_pixmap(None)
        self.mesh_preview.clear()
        if show_placeholder:
            self._show_mesh_placeholder()
        else:
            self.mesh_hint.hide()

    def clear_all(self) -> None:
        self.clear_tpose_preview()
        self.clear_mesh_preview()

    def _show_mesh_placeholder(self, message: str | None = None) -> None:
        self.mesh_preview.set_source_pixmap(None)
        self.mesh_preview.clear()
        self.mesh_hint.setText(message or self._MESH_PLACEHOLDER)
        self.mesh_hint.show()
