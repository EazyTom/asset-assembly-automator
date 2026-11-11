from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from asset_assembly_automator.clients.meshy_client import RETEXTURE_PROMPT_MAX_CHARS
from asset_assembly_automator.gui.widgets.zoom_preview_label import (
    ZoomPreviewLabel,
    configure_zoom_scroll_area,
)


class MeshReviewView(QWidget):
    retextureRequested = pyqtSignal(str, str)
    approveRequested = pyqtSignal(str)
    reviewToggled = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        self.status = QLabel("Select a pipeline")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.review_check = QCheckBox("Pause for mesh review after image-to-3D")
        self.review_check.toggled.connect(self.reviewToggled.emit)
        root.addWidget(self.review_check)

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
        self.preview_meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview_layout.addWidget(self.preview_meta)
        split.addWidget(preview_host)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        root.addWidget(split, stretch=1)

        self.approve_btn = QPushButton("Approve selected && continue")
        self.approve_btn.clicked.connect(self._approve)
        root.addWidget(self.approve_btn)

        root.addWidget(QLabel("New texture variant (same geometry)"))
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(
            "Describe the texture, e.g. weathered bronze armor, worn leather straps"
        )
        self.prompt.setFixedHeight(70)
        self.prompt.textChanged.connect(self._update_counter)
        root.addWidget(self.prompt)
        image_row = QHBoxLayout()
        self.style_image = QLineEdit()
        self.style_image.setPlaceholderText("Optional style image (used instead of the prompt)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        image_row.addWidget(self.style_image, 1)
        image_row.addWidget(browse)
        root.addLayout(image_row)
        retex_row = QHBoxLayout()
        self.counter = QLabel("")
        self.retexture_btn = QPushButton("Retexture")
        self.retexture_btn.clicked.connect(self._retexture)
        retex_row.addWidget(self.counter, 1)
        retex_row.addWidget(self.retexture_btn)
        root.addLayout(retex_row)
        hint = QLabel(
            "Each variant is a Meshy Retexture task (~10 credits, 15 at 8K; failed tasks are "
            "refunded). Approving a variant makes it the mesh used for remesh, rig, and export."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        self._update_counter()

    def load(
        self,
        pipe: Any | None,
        variants: list[dict],
        *,
        original_preview: Path | None,
        review_enabled: bool,
    ) -> None:
        self.review_check.blockSignals(True)
        self.review_check.setChecked(review_enabled)
        self.review_check.blockSignals(False)
        self.list.blockSignals(True)
        self.list.clear()
        if pipe is None:
            self.status.setText("Select a pipeline")
            self.list.blockSignals(False)
            self._show(None)
            return
        source = (pipe.metadata or {}).get("mesh_source") or {}
        approved_id = source.get("task_id")
        if pipe.current_stage == "mesh_review":
            self.status.setText(
                "Waiting for mesh review — retexture as needed, then approve a mesh to continue."
            )
        else:
            self.status.setText(f"Current stage: {pipe.current_stage}")
        retex_n = 0
        for job in variants:
            meta = job.get("metadata") or {}
            if job["task_type"] == "image-to-3d":
                label = "Original (image-to-3D)"
                preview = str(original_preview) if original_preview else ""
            else:
                retex_n += 1
                desc = meta.get("prompt") or Path(meta.get("style_image_path") or "").name
                label = f"Retexture #{retex_n}: {desc[:60]}"
                preview = meta.get("thumbnail_path") or ""
            if job["task_id"] == approved_id:
                label = f"✔ {label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, {**job, "preview_path": preview})
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.list.count():
            self.list.setCurrentRow(self.list.count() - 1)
        else:
            self._show(None)

    def _preview_selected(self, current: QListWidgetItem | None, _previous) -> None:
        self._show(current.data(Qt.ItemDataRole.UserRole) if current else None)

    def _show(self, job: dict | None) -> None:
        self.approve_btn.setEnabled(job is not None)
        if not job:
            self.preview_label.set_source_pixmap(None)
            self.preview_label.setText("No finished meshes yet. Run Meshy image-to-3D first.")
            self.preview_meta.setText("")
            return
        meta = job.get("metadata") or {}
        path = job.get("preview_path") or ""
        pixmap = QPixmap(path) if path and Path(path).is_file() else QPixmap()
        if pixmap.isNull():
            self.preview_label.set_source_pixmap(None)
            self.preview_label.setText("No preview image for this mesh.")
        else:
            self.preview_label.set_source_pixmap(
                pixmap.scaled(
                    512,
                    512,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        lines = [f"Task: {job['task_id']} ({job['task_type']})"]
        if job.get("credits_used"):
            lines.append(f"Credits: {job['credits_used']:g}")
        if meta.get("prompt"):
            lines.append(f"Prompt: {meta['prompt']}")
        if meta.get("style_image_path"):
            lines.append(f"Style image: {meta['style_image_path']}")
        self.preview_meta.setText("\n".join(lines))

    def _update_counter(self) -> None:
        n = len(self.prompt.toPlainText().strip())
        self.counter.setText(f"{n}/{RETEXTURE_PROMPT_MAX_CHARS} characters")
        self.counter.setStyleSheet("color: #d9534f;" if n > RETEXTURE_PROMPT_MAX_CHARS else "")

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Style image", "", "Images (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            self.style_image.setText(path)

    def _retexture(self) -> None:
        prompt = self.prompt.toPlainText().strip()
        image = self.style_image.text().strip()
        if not prompt and not image:
            self.counter.setText("Enter a prompt or choose a style image")
            return
        if len(prompt) > RETEXTURE_PROMPT_MAX_CHARS:
            return
        self.retextureRequested.emit(prompt, image)

    def _approve(self) -> None:
        item = self.list.currentItem()
        job = item.data(Qt.ItemDataRole.UserRole) if item else None
        if job:
            self.approveRequested.emit(str(job["task_id"]))
