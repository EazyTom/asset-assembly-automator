from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.logging import pipeline_log_dir
from asset_assembly_automator.core.output_paths import get_output_dirs
from asset_assembly_automator.gui.theme.theme import LOG_LEVEL_COLORS


class LogViewer(QWidget):
    COLUMNS = ("Time", "Level", "Stage", "Duration", "Message")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pipeline_id: int | None = None
        self._pipeline_name = ""
        self._db: Database | None = None
        self._entries: list[dict[str, Any]] = []
        self._last_id = 0

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title = QLabel("Pipeline Log")
        self.title.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(self.title, stretch=1)

        self.level_filter = QComboBox()
        self.level_filter.addItems(["All levels", "info", "warning", "error", "debug"])
        self.level_filter.currentTextChanged.connect(self._apply_filter)
        header.addWidget(self.level_filter)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter messages…")
        self.search.textChanged.connect(self._apply_filter)
        header.addWidget(self.search, stretch=1)

        self.auto_scroll = QCheckBox("Auto-scroll")
        self.auto_scroll.setChecked(True)
        header.addWidget(self.auto_scroll)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)

        self.open_folder_btn = QPushButton("Open log folder")
        self.open_folder_btn.clicked.connect(self._open_log_folder)
        header.addWidget(self.open_folder_btn)

        layout.addLayout(header)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(list(self.COLUMNS))
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.summary = QLabel("Select a pipeline to view its log history.")
        layout.addWidget(self.summary)

    @property
    def last_id(self) -> int:
        return self._last_id

    def set_database(self, db: Database) -> None:
        self._db = db

    def clear(self) -> None:
        self._pipeline_id = None
        self._pipeline_name = ""
        self._last_id = 0
        self._entries.clear()
        self.table.setRowCount(0)
        self.title.setText("Pipeline Log")
        self.summary.setText("")

    def load_pipeline(self, pipeline_id: int, pipeline_name: str) -> None:
        self._pipeline_id = pipeline_id
        self._pipeline_name = pipeline_name
        self._last_id = 0
        self._entries.clear()
        self.table.setRowCount(0)
        if not self._db:
            return
        logs = self._db.get_logs_since(pipeline_id, since_id=0)
        self.append_entries(logs)
        self._update_title()

    def refresh(self) -> None:
        if self._pipeline_id is None or not self._db:
            return
        logs = self._db.get_logs_since(self._pipeline_id, since_id=self._last_id)
        self.append_entries(logs)

    def append_entries(self, entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            self._append_entry(entry)

    def append_entry(self, entry: dict[str, Any]) -> None:
        self._append_entry(entry)

    def append(self, level: str, message: str, *, stage: str = "", created_at: str = "") -> None:
        self._append_entry(
            {
                "id": self._last_id + 1,
                "level": level,
                "message": message,
                "created_at": created_at,
                "context": {"stage": stage},
            }
        )

    def _append_entry(self, entry: dict[str, Any]) -> None:
        entry_id = entry.get("id")
        if entry_id is not None and entry_id <= self._last_id:
            return
        self._entries.append(entry)
        if entry_id is not None:
            self._last_id = max(self._last_id, int(entry_id))
        self._apply_filter(single_new=entry)

    def _stage_for(self, entry: dict[str, Any]) -> str:
        ctx = entry.get("context") or {}
        return str(ctx.get("stage") or entry.get("stage") or "")

    def _format_time(self, entry: dict[str, Any]) -> str:
        raw = entry.get("created_at") or entry.get("timestamp") or ""
        if not raw:
            return ""
        return raw.replace("T", " ").split("+")[0].split(".")[0]

    def _apply_filter(self, *_args, single_new: dict[str, Any] | None = None) -> None:
        level = self.level_filter.currentText()
        query = self.search.text().strip().lower()

        if single_new is not None and self._entry_visible(single_new, level, query):
            self._insert_row(single_new)
            if self.auto_scroll.isChecked():
                self.table.scrollToBottom()
            self._update_title()
            return

        self.table.setRowCount(0)
        for entry in self._entries:
            if self._entry_visible(entry, level, query):
                self._insert_row(entry)
        if self.auto_scroll.isChecked():
            self.table.scrollToBottom()
        self._update_title()

    def _entry_visible(self, entry: dict[str, Any], level: str, query: str) -> bool:
        if level != "All levels" and entry.get("level", "").lower() != level:
            return False
        if query:
            hay = " ".join(
                [
                    self._format_time(entry),
                    entry.get("level", ""),
                    self._stage_for(entry),
                    entry.get("message", ""),
                ]
            ).lower()
            if query not in hay:
                return False
        return True

    def _duration_for(self, entry: dict[str, Any]) -> str:
        ctx = entry.get("context") or {}
        raw = ctx.get("duration_ms")
        if raw is None:
            return ""
        try:
            return f"{int(raw)} ms"
        except (TypeError, ValueError):
            return str(raw)

    def _insert_row(self, entry: dict[str, Any]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            self._format_time(entry),
            entry.get("level", ""),
            self._stage_for(entry),
            self._duration_for(entry),
            entry.get("message", ""),
        ]
        for col, text in enumerate(values):
            item = QTableWidgetItem(str(text))
            if col == 1:
                color = LOG_LEVEL_COLORS.get(str(text).lower(), "#CBD5E1")
                item.setForeground(QColor(color))
            item.setData(Qt.ItemDataRole.UserRole, entry.get("id"))
            self.table.setItem(row, col, item)

    def _update_title(self) -> None:
        name = self._pipeline_name or "Pipeline"
        visible = self.table.rowCount()
        total = len(self._entries)
        suffix = f" — {visible}/{total} entries" if visible != total else f" — {total} entries"
        self.title.setText(f"Pipeline Log: {name}{suffix if total else ''}")
        if self._db and self._pipeline_id:
            summary = self._db.get_log_summary(self._pipeline_id)
            last = summary.get("last_message") or "No messages yet"
            self.summary.setText(f"Last: {last}")

    def _open_log_folder(self) -> None:
        if self._pipeline_id is None or not self._db:
            return
        try:
            dirs = get_output_dirs(self._db, self._pipeline_id)
            folder = pipeline_log_dir(dirs["root"], self._pipeline_id)
        except ValueError:
            return
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
