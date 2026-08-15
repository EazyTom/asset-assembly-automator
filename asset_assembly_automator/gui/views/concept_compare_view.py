from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from asset_assembly_automator.clients.concept_images import is_valid_image
from asset_assembly_automator.gui.widgets.zoom_preview_label import (
    ZoomPreviewLabel,
    configure_zoom_scroll_area,
)


class ConceptCompareView(QWidget):
    approveRequested = pyqtSignal(int, str)
    refineRequested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._assets: list[dict] = []
        root = QVBoxLayout(self)
        root.addWidget(QLabel("Concept candidates — preview native images, then approve"))

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._preview_selected)
        split.addWidget(self.list)

        preview_host = QWidget()
        preview_layout = QVBoxLayout(preview_host)
        self.preview_scroll = QScrollArea()
        self.preview_label = ZoomPreviewLabel()
        configure_zoom_scroll_area(self.preview_scroll, self.preview_label)
        preview_layout.addWidget(self.preview_scroll)
        self.preview_meta = QLabel("")
        self.preview_meta.setWordWrap(True)
        preview_layout.addWidget(self.preview_meta)
        split.addWidget(preview_host)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        root.addWidget(split, stretch=1)

        self.approve_btn = QPushButton("Approve selected && continue")
        self.refine_btn = QPushButton("Refine (re-generate concept)")
        self.approve_btn.clicked.connect(self._approve)
        self.refine_btn.clicked.connect(self.refineRequested.emit)
        root.addWidget(self.approve_btn)
        root.addWidget(self.refine_btn)
        self.hint = QLabel(
            "Preview native concept images first (Midjourney import, drop, or optional Higgs/Magnific generate). "
            "Scroll the mouse wheel to zoom toward the cursor. Click and drag to pan. "
            "Approve the best T-pose — Magnific uprez then Meshy run automatically after approval."
        )
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

    def load_assets(self, assets: list[dict]) -> None:
        self._assets = assets
        self.list.blockSignals(True)
        self.list.clear()
        for asset in assets:
            path = asset.get("file_path", "")
            valid = is_valid_image(path) if path else False
            status = "ok" if valid else "invalid"
            label = f"[{asset.get('provider', '?')}] [{status}] {Path(path).name if path else '?'}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, asset)
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self._show_preview(None)

    def _preview_selected(self, current: QListWidgetItem | None, _previous) -> None:
        if current is None:
            self._show_preview(None)
            return
        asset = current.data(Qt.ItemDataRole.UserRole) or {}
        self._show_preview(asset)

    def _show_preview(self, asset: dict | None) -> None:
        if not asset:
            self.preview_label.setText(
                "No concept images yet.\n"
                "Import or drop a PNG, or click Refine to generate with Higgsfield.\n"
                "Preview here first — Magnific uprez runs after you approve."
            )
            self.preview_label.set_source_pixmap(None)
            self.preview_meta.setText("")
            return

        path = asset.get("file_path", "")
        provider = asset.get("provider", "?")
        if not path or not Path(path).exists():
            self.preview_label.setText(f"File missing:\n{path}")
            self.preview_label.set_source_pixmap(None)
            self.preview_meta.setText(f"Provider: {provider}")
            return

        if not is_valid_image(path):
            self.preview_label.setText(
                "Invalid or corrupt image file.\n"
                "Re-run concept generation with valid Higgsfield credentials."
            )
            self.preview_label.set_source_pixmap(None)
            self.preview_meta.setText(f"Provider: {provider}\nPath: {path}")
            return

        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self.preview_label.setText("Could not load image preview.")
            self.preview_label.set_source_pixmap(None)
        else:
            base = pixmap.scaled(
                480,
                720,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_label.set_source_pixmap(base)
        self.preview_meta.setText(f"Provider: {provider}\nPath: {path}")

    def _approve(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        asset = item.data(Qt.ItemDataRole.UserRole) or {}
        asset_id = asset.get("id")
        path = asset.get("file_path", "")
        if not asset_id:
            return
        if not path or not is_valid_image(path):
            self.preview_label.setText(
                "Cannot approve invalid concept image.\nGenerate or import a valid PNG first."
            )
            return
        provider = str(asset.get("provider") or "higgsfield")
        self.approveRequested.emit(int(asset_id), provider)
