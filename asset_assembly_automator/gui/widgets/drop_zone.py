from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPixmap
from PyQt6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from asset_assembly_automator.gui.widgets.zoom_preview_label import (
    ZoomPreviewLabel,
    configure_zoom_scroll_area,
)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class DropZone(QWidget):
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(280)
        layout = QVBoxLayout(self)
        self.label = QLabel("Drop pre-approved T-pose character art here\n(PNG, JPG, WEBP)")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setMinimumHeight(200)
        self.preview_label = ZoomPreviewLabel()
        self.preview_label.setMinimumSize(240, 180)
        configure_zoom_scroll_area(self.preview_scroll, self.preview_label)
        layout.addWidget(self.label)
        layout.addWidget(self.preview_scroll, stretch=1)
        self._set_idle_style()

    def _set_idle_style(self) -> None:
        self.setStyleSheet(
            "DropZone { border: 2px dashed #585b70; border-radius: 12px; background: #1e1e2e; }"
        )

    def _set_active_style(self) -> None:
        self.setStyleSheet(
            "DropZone { border: 2px dashed #89b4fa; border-radius: 12px; background: #181825; }"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and self._extract_paths(event.mimeData().urls()):
            event.acceptProposedAction()
            self._set_active_style()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_idle_style()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        paths = self._extract_paths(event.mimeData().urls())
        self._set_idle_style()
        if not paths:
            event.ignore()
            return
        self._show_preview(paths[0])
        self.label.setText(f"{len(paths)} file(s) ready — scroll wheel to zoom, drag to pan")
        self.filesDropped.emit(paths)
        event.acceptProposedAction()

    def _extract_paths(self, urls) -> list[str]:
        paths: list[str] = []
        for url in urls:
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in _IMAGE_SUFFIXES and path.is_file():
                paths.append(str(path))
        return paths

    # Cap the working source so zoom stays crisp without unbounded memory for
    # very large textures (4K+). The zoom label fits this to the viewport and
    # zooms from full resolution, so detail is preserved up to this size.
    _MAX_PREVIEW_DIM = 2560

    def _show_preview(self, path: str) -> None:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.preview_label.set_source_pixmap(None)
            self.preview_label.setText("Could not load image preview.")
            return
        if pixmap.width() > self._MAX_PREVIEW_DIM or pixmap.height() > self._MAX_PREVIEW_DIM:
            pixmap = pixmap.scaled(
                self._MAX_PREVIEW_DIM,
                self._MAX_PREVIEW_DIM,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.preview_label.set_source_pixmap(pixmap)

    def clear_preview(self) -> None:
        self.preview_label.set_source_pixmap(None)
        self.preview_label.clear()
        self.label.setText("Drop pre-approved T-pose character art here\n(PNG, JPG, WEBP)")
        self._set_idle_style()
