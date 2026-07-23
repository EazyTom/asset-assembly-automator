from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QMouseEvent, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QLabel, QScrollArea


class _ZoomWheelFilter(QObject):
    """Forward viewport wheel events to the preview label for cursor-centered zoom."""

    def __init__(self, preview: ZoomPreviewLabel) -> None:
        super().__init__(preview)
        self._preview = preview

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Wheel and self._preview._has_image():
            self._preview.wheelEvent(event)
            return True
        return super().eventFilter(obj, event)


class ZoomPreviewLabel(QLabel):
    """Image preview with cursor-anchored wheel zoom and click-drag panning."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scroll_area: QScrollArea | None = None
        self._source: QPixmap | None = None
        self._zoom = 1.0
        self._dragging = False
        self._drag_start = None
        self._scroll_start = (0, 0)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 480)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.WheelFocus)
        self.setStyleSheet(
            "QLabel { background-color: #1e1e2e; border: 1px solid #313244; border-radius: 8px; }"
        )

    def set_scroll_area(self, scroll_area: QScrollArea) -> None:
        self._scroll_area = scroll_area

    def set_source_pixmap(self, pixmap: QPixmap | None) -> None:
        self._source = pixmap
        self._dragging = False
        self._zoom = self._fit_zoom()
        if self._scroll_area is not None:
            self._scroll_area.horizontalScrollBar().setValue(0)
            self._scroll_area.verticalScrollBar().setValue(0)
        self._apply_zoom()
        self._update_cursor()

    def _has_image(self) -> bool:
        return self._source is not None and not self._source.isNull()

    def _fit_zoom(self) -> float:
        """Scale that fits the full-resolution source inside the viewport.

        Never enlarges small images past native (cap at 1.0); large images are
        scaled down to fit. Wheel zoom multiplies from this base so zooming in
        reveals real detail up to (and past) native resolution instead of
        upscaling a pre-shrunk thumbnail.
        """
        if not self._has_image() or self._scroll_area is None:
            return 1.0
        viewport = self._scroll_area.viewport().size()
        src_w = self._source.width()
        src_h = self._source.height()
        if viewport.width() <= 0 or viewport.height() <= 0 or src_w <= 0 or src_h <= 0:
            return 1.0
        fit = min(viewport.width() / src_w, viewport.height() / src_h)
        return min(max(fit, 0.02), 1.0)

    def _zoom_bounds(self) -> tuple[float, float]:
        fit = self._fit_zoom()
        min_zoom = min(fit, 1.0) * 0.5
        max_zoom = max(fit, 1.0) * 6.0
        return min_zoom, max_zoom

    def _update_cursor(self) -> None:
        if self._dragging:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif self._has_image():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._has_image() or self._scroll_area is None:
            event.ignore()
            return

        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return

        factor = 1.1 if delta > 0 else 1 / 1.1
        old_zoom = self._zoom
        min_zoom, max_zoom = self._zoom_bounds()
        new_zoom = max(min_zoom, min(max_zoom, old_zoom * factor))
        if new_zoom == old_zoom:
            event.accept()
            return

        scroll = self._scroll_area
        viewport = scroll.viewport()
        viewport_pos = viewport.mapFromGlobal(event.globalPosition().toPoint())
        label_pos = self.mapFromGlobal(event.globalPosition().toPoint())
        anchor_x = label_pos.x()
        anchor_y = label_pos.y()
        scale = new_zoom / old_zoom

        self._zoom = new_zoom
        self._apply_zoom()

        scroll.horizontalScrollBar().setValue(int(anchor_x * scale - viewport_pos.x()))
        scroll.verticalScrollBar().setValue(int(anchor_y * scale - viewport_pos.y()))
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._has_image()
            and self._scroll_area is not None
        ):
            self._dragging = True
            self._drag_start = event.globalPosition().toPoint()
            scroll = self._scroll_area
            self._scroll_start = (
                scroll.horizontalScrollBar().value(),
                scroll.verticalScrollBar().value(),
            )
            self.grabMouse()
            self._update_cursor()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._drag_start is not None and self._scroll_area is not None:
            delta = event.globalPosition().toPoint() - self._drag_start
            scroll = self._scroll_area
            scroll.horizontalScrollBar().setValue(self._scroll_start[0] - delta.x())
            scroll.verticalScrollBar().setValue(self._scroll_start[1] - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_start = None
            self.releaseMouse()
            self._update_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _apply_zoom(self) -> None:
        if not self._has_image():
            self.setPixmap(QPixmap())
            self._update_cursor()
            return
        width = max(1, int(self._source.width() * self._zoom))
        height = max(1, int(self._source.height() * self._zoom))
        scaled = self._source.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)
        self.setText("")
        self.resize(scaled.size())
        self._update_cursor()


def configure_zoom_scroll_area(scroll: QScrollArea, preview: ZoomPreviewLabel) -> None:
    """Wire a scroll area for top-left anchored zoom/pan math."""
    preview.set_scroll_area(scroll)
    scroll.setWidgetResizable(False)
    scroll.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    scroll.setWidget(preview)
    scroll.viewport().installEventFilter(_ZoomWheelFilter(preview))
