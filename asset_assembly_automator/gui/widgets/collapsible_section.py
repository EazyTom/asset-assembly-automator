from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class _SectionHeader(QWidget):
    clicked = pyqtSignal()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        if event and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class CollapsibleSection(QWidget):
    """Section with a clickable header that shows or hides its body."""

    toggled = pyqtSignal(bool)

    def __init__(self, title: str, *, expanded: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._expanded = expanded

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        header = _SectionHeader()
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.clicked.connect(lambda: self.set_expanded(not self._expanded))
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        self.toggle_btn = QToolButton()
        self.toggle_btn.setAutoRaise(True)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(expanded)
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)

        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)

        header_layout.addWidget(self.toggle_btn)
        header_layout.addWidget(self.title_label, stretch=1)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(16, 0, 0, 0)

        root.addWidget(header)
        root.addWidget(self.content)
        self._apply_expanded_state(expanded, notify=False)

    def add_widget(self, widget: QWidget) -> None:
        self.content_layout.addWidget(widget)

    def add_layout(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        self.content_layout.addLayout(layout)

    def set_expanded(self, expanded: bool) -> None:
        if expanded == self._expanded:
            return
        self._apply_expanded_state(expanded, notify=True)

    def is_expanded(self) -> bool:
        return self._expanded

    def _on_toggle_clicked(self, checked: bool) -> None:
        self.set_expanded(checked)

    def _apply_expanded_state(self, expanded: bool, *, notify: bool) -> None:
        self._expanded = expanded
        self.toggle_btn.blockSignals(True)
        self.toggle_btn.setChecked(expanded)
        self.toggle_btn.blockSignals(False)
        self.toggle_btn.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.content.setVisible(expanded)
        if notify:
            self.toggled.emit(expanded)
