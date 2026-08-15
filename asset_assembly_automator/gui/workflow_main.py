from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import qasync
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QFontMetrics
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from asset_assembly_automator import __version__
from asset_assembly_automator.core.db.models import Database, local_database_path
from asset_assembly_automator.core.output_paths import (
    character_name_slug,
    character_output_root,
    display_name_from_filename,
    ensure_pipeline_output_slug,
    get_output_dirs,
    pipeline_character_slug,
    project_output_slug,
)
from asset_assembly_automator.core.state_machine import StageId, stage_index
from asset_assembly_automator.gui.controller import PipelineController
from asset_assembly_automator.gui.executor import get_executor
from asset_assembly_automator.gui.theme.theme import load_theme_pref, setup_theme
from asset_assembly_automator.gui.views.log_viewer import LogViewer
from asset_assembly_automator.gui.widgets.character_preview_panel import CharacterPreviewPanel
from asset_assembly_automator.gui.widgets.collapsible_section import CollapsibleSection
from asset_assembly_automator.gui.widgets.pipeline_stepper import (
    MeshyWorkflowStepper,
    stage_display_label,
)
from asset_assembly_automator.workflow.templates import UNITY_IMPORT_TEMPLATE_PLACEHOLDERS

CONCEPT_PROMPT_TEMPLATE = (
    "<character description here> full body T-pose, front view, orthographic character sheet, "
    "symmetrical design, <head desc>, <outfit description, colors>, arms straight out "
    "horizontally, legs slightly apart, clean silhouette, neutral expression, "
    "game-ready HD photo-realistic, plain white background, no weapons, no props, "
    "no text, no watermark"
)


class WorkflowWindow(QMainWindow):
    def __init__(self, loop: qasync.QEventLoop, *, dry_run: bool = False) -> None:
        super().__init__()
        self.loop = loop
        self.dry_run = dry_run
        self.db = Database()
        self.controller = PipelineController(self.db, dry_run=dry_run)
        self._selected_pipeline: int | None = None
        self._selected_project_id: int | None = None
        self._last_drop_path: str | None = None
        self._pending_drop_path: str | None = None
        self._pending_already_uprezzed = False
        self._saved_character_name: str | None = None
        self._saved_unity_prompt: str | None = None
        self._last_log_id = 0

        title = f"AAA Meshy Workflow v{__version__}"
        if dry_run:
            title += " [DRY RUN]"
        self.setWindowTitle(title)
        self.resize(1180, 860)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)

        config_box = QGroupBox("Project settings")
        form = QFormLayout(config_box)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        def _field_row(*widgets: QWidget) -> QWidget:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            for index, widget in enumerate(widgets):
                if index == 0:
                    widget.setSizePolicy(
                        QSizePolicy.Policy.Expanding,
                        QSizePolicy.Policy.Fixed,
                    )
                    layout.addWidget(widget, stretch=1)
                else:
                    layout.addWidget(widget)
            return row

        self.project_combo = QComboBox()
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        new_project_btn = QPushButton("New…")
        new_project_btn.clicked.connect(self._new_project)
        form.addRow("Project", _field_row(self.project_combo, new_project_btn))

        self.project_slug_label = QLineEdit()
        self.project_slug_label.setReadOnly(True)
        self.project_slug_label.setPlaceholderText("project-slug")
        form.addRow("Project slug", self.project_slug_label)

        self.character_name = QLineEdit()
        self.character_name.setPlaceholderText("Character name (slugged for folders)")
        self.character_name.textChanged.connect(self._on_character_name_changed)
        self.save_character_btn = QPushButton("Save")
        self.save_character_btn.setEnabled(False)
        self.save_character_btn.clicked.connect(self._save_character_name)
        self.new_character_btn = QPushButton("New…")
        self.new_character_btn.setToolTip(
            "Register a new character in this project (creates DB entry + output "
            "folders). Drop T-pose art afterwards, then Run Meshy."
        )
        self.new_character_btn.clicked.connect(self._new_character)
        form.addRow(
            "Character name",
            _field_row(self.character_name, self.save_character_btn, self.new_character_btn),
        )

        self.character_slug_label = QLineEdit()
        self.character_slug_label.setReadOnly(True)
        self.character_slug_label.setPlaceholderText("character-slug")
        form.addRow("Character slug", self.character_slug_label)

        self.output_root_label = QLineEdit()
        self.output_root_label.setReadOnly(True)
        self.output_root_label.setPlaceholderText("{output_root}/{project_slug}-{character_slug}")
        output_browse = QPushButton("Browse…")
        output_browse.clicked.connect(self._browse_output_folder)
        form.addRow("Output folder", _field_row(self.output_root_label, output_browse))

        self.unity_path = QLineEdit()
        self.unity_path.setPlaceholderText("Path to Unity project root")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_unity_path)
        form.addRow("Unity project", _field_row(self.unity_path, browse))

        self.poly_budget = QComboBox()
        self.poly_budget.addItems(["hero", "npc", "crowd"])
        self.poly_budget.setCurrentText("hero")
        self.poly_budget.setToolTip(
            "Meshy poly target (all budgets use API max 300k tris + 4K HD textures). "
            "Lower remesh/i2d targets in user config.yaml to reduce credits or LOD."
        )
        form.addRow("Poly budget", self.poly_budget)

        self.texture_prompt = QPlainTextEdit()
        self.texture_prompt.setPlaceholderText(
            "Optional Meshy texture/style prompt passed to image-to-3D and retexture stages"
        )
        texture_line_height = QFontMetrics(self.texture_prompt.font()).lineSpacing()
        self.texture_prompt.setFixedHeight(texture_line_height * 4 + 12)
        form.addRow("Texture prompt", self.texture_prompt)

        for widget in (
            self.project_slug_label,
            self.character_slug_label,
            self.poly_budget,
        ):
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        header_layout.addWidget(config_box, stretch=1)

        concept_box = QGroupBox("Concept Image")
        concept_layout = QVBoxLayout(concept_box)
        self.concept_prompt = QPlainTextEdit()
        self.concept_prompt.setPlainText(CONCEPT_PROMPT_TEMPLATE)
        concept_line_height = QFontMetrics(self.concept_prompt.font()).lineSpacing()
        self.concept_prompt.setFixedHeight(concept_line_height * 6 + 12)
        concept_layout.addWidget(self.concept_prompt)

        gen_btn_row = QHBoxLayout()
        self.use_higgs_btn = QPushButton("Use Higgs")
        self.use_higgs_btn.clicked.connect(self._on_use_higgs)
        self.use_magnific_btn = QPushButton("Use Magnific")
        self.use_magnific_btn.clicked.connect(self._on_use_magnific)
        gen_btn_row.addWidget(self.use_higgs_btn)
        gen_btn_row.addWidget(self.use_magnific_btn)
        concept_layout.addLayout(gen_btn_row)
        preview_hint = QLabel(
            "Preview native concepts first (drop / Higgs / Magnific generate). "
            "Magnific uprez runs automatically after Save, before Meshy."
        )
        preview_hint.setWordWrap(True)
        concept_layout.addWidget(preview_hint)

        uprez_row = QHBoxLayout()
        self.uprez_mode = QComboBox()
        self.uprez_mode.addItem("Precision V2 (faithful)", "precision_v2")
        self.uprez_mode.addItem("Creative (prompt-guided)", "creative")
        self.uprez_scale = QComboBox()
        for scale in ("2x", "4x", "8x", "16x"):
            self.uprez_scale.addItem(scale, scale)
        self.uprez_flavor = QComboBox()
        self.uprez_flavor.addItem("sublime", "sublime")
        self.uprez_flavor.addItem("photo", "photo")
        self.uprez_flavor.addItem("photo_denoiser", "photo_denoiser")
        self.uprez_btn = QPushButton("Preview uprez")
        self.uprez_btn.setToolTip(
            "Optional: preview Magnific upscale before Save. "
            "Uprez still runs automatically after approval unless you already previewed it."
        )
        self.uprez_btn.clicked.connect(self._on_uprez)
        self.uprez_mode.currentIndexChanged.connect(self._on_uprez_mode_changed)
        uprez_row.addWidget(self.uprez_mode)
        uprez_row.addWidget(self.uprez_scale)
        uprez_row.addWidget(self.uprez_flavor)
        uprez_row.addWidget(self.uprez_btn)
        concept_layout.addLayout(uprez_row)
        self._apply_magnific_ui_defaults()

        header_layout.addWidget(concept_box, stretch=1)

        self.preview_panel = CharacterPreviewPanel()
        self.preview_panel.filesDropped.connect(self._on_files_dropped)
        header_layout.addWidget(self.preview_panel, stretch=1)

        split = QSplitter(Qt.Orientation.Vertical)
        mid = QWidget()
        mid_layout = QVBoxLayout(mid)

        character_row = QHBoxLayout()
        character_row.addWidget(QLabel("Character"))
        self.pipeline_combo = QComboBox()
        self.pipeline_combo.setMinimumWidth(280)
        self.pipeline_combo.setPlaceholderText("Saved characters — drop art, name, and Save first")
        self.pipeline_combo.currentIndexChanged.connect(self._on_pipeline_selected)
        character_row.addWidget(self.pipeline_combo, stretch=1)
        self.delete_character_btn = QPushButton("Delete character")
        self.delete_character_btn.setToolTip(
            "Permanently delete this character, its output folder, and all local database records"
        )
        self.delete_character_btn.clicked.connect(self._delete_character)
        self.delete_character_btn.setEnabled(False)
        character_row.addWidget(self.delete_character_btn)
        mid_layout.addLayout(character_row)

        self.stepper = MeshyWorkflowStepper()
        mid_layout.addWidget(self.stepper)
        self.status_label = QLineEdit()
        self.status_label.setReadOnly(True)
        mid_layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.run_meshy_btn = QPushButton("Run Meshy")
        self.run_meshy_btn.clicked.connect(self._run_meshy)
        self.download_meshy_btn = QPushButton("Download from Meshy")
        self.download_meshy_btn.setToolTip(
            "Re-download FBX, walk/run, and textures from the existing Meshy rig task (0 credits)"
        )
        self.download_meshy_btn.clicked.connect(self._download_from_meshy)
        self.download_meshy_btn.setEnabled(False)
        self.import_btn = QPushButton("Import to Unity (Cursor MCP)")
        self.import_btn.clicked.connect(self._import_unity)
        self.import_btn.setEnabled(False)
        self.cleanup_unity_btn = QPushButton("Remove from Unity (Cursor MCP)")
        self.cleanup_unity_btn.setToolTip(
            "Delete this character's Unity assets and scene instance via Cursor CLI + Unity MCP"
        )
        self.cleanup_unity_btn.clicked.connect(self._cleanup_unity)
        self.cleanup_unity_btn.setEnabled(False)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(self.run_meshy_btn)
        btn_row.addWidget(self.download_meshy_btn)
        btn_row.addWidget(self.import_btn)
        btn_row.addWidget(self.cleanup_unity_btn)
        btn_row.addWidget(self.cancel_btn)
        mid_layout.addLayout(btn_row)

        placeholder_help = ", ".join(f"{{{name}}}" for name in UNITY_IMPORT_TEMPLATE_PLACEHOLDERS)
        prompt_section = CollapsibleSection(
            "Unity import prompt template (saved per character → Cursor CLI)",
            expanded=True,
        )
        prompt_help = QLabel(
            "Edit the agent instructions below. Placeholders "
            f"{placeholder_help} are expanded at import time. Save before Import."
        )
        prompt_help.setWordWrap(True)
        prompt_section.add_widget(prompt_help)
        self.unity_prompt = QPlainTextEdit()
        self.unity_prompt.setPlaceholderText("Loading Unity import template…")
        self._saved_unity_prompt = ""
        self.unity_prompt.setMinimumHeight(180)
        self.unity_prompt.textChanged.connect(self._on_unity_prompt_changed)
        prompt_section.add_widget(self.unity_prompt)
        prompt_btn_row = QHBoxLayout()
        self.save_unity_prompt_btn = QPushButton("Save prompt")
        self.save_unity_prompt_btn.setEnabled(False)
        self.save_unity_prompt_btn.clicked.connect(self._save_unity_prompt)
        reset_prompt = QPushButton("Reset to default")
        reset_prompt.clicked.connect(self._reset_unity_prompt)
        prompt_btn_row.addWidget(self.save_unity_prompt_btn)
        prompt_btn_row.addWidget(reset_prompt)
        prompt_btn_row.addStretch(1)
        prompt_section.add_layout(prompt_btn_row)
        mid_layout.addWidget(prompt_section)
        split.addWidget(mid)

        self.log_viewer = LogViewer()
        self.log_viewer.set_database(self.db)
        split.addWidget(self.log_viewer)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        outer_split = QSplitter(Qt.Orientation.Vertical)
        outer_split.addWidget(header)
        outer_split.addWidget(split)
        outer_split.setStretchFactor(0, 2)
        outer_split.setStretchFactor(1, 3)
        outer_split.setSizes([360, 500])
        root.addWidget(outer_split, stretch=1)

        toolbar = self.addToolBar("Workflow")
        toolbar.addAction("New project", self._new_project)
        refresh_act = toolbar.addAction("Refresh projects")
        refresh_act.triggered.connect(lambda: self.refresh_projects())

        self._setup_menu()

        self.controller.stageProgress.connect(self._on_progress)
        self.controller.stageFinished.connect(self._on_finished)
        self.controller.logEntryAdded.connect(self._on_log_entry)
        self.controller.runBlocked.connect(self._on_run_blocked)
        self.controller.pipelineUpdated.connect(self._on_pipeline_updated)

        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._poll_logs)
        self.refresh_timer.start(1500)

        QTimer.singleShot(0, self._finish_startup)

    def _finish_startup(self) -> None:
        from asset_assembly_automator.workflow.templates import load_unity_import_template

        default_prompt = load_unity_import_template()
        self._set_unity_prompt_text(default_prompt, saved=True)
        self.refresh_projects()

    def _setup_menu(self) -> None:
        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction("Delete project…", self._delete_project)
        tools_menu.addAction("Reset local database…", self._reset_local_database)
        tools_menu.addAction("Delete output directory…", self._delete_output_directory)

    def _delete_project(self) -> None:
        if not self._selected_project_id:
            QMessageBox.information(self, "Delete project", "Select a project first.")
            return

        project = self.db.get_project(self._selected_project_id)
        if not project:
            QMessageBox.warning(self, "Delete project", "Project not found in the database.")
            self.refresh_projects()
            return

        pipes = self.db.list_pipelines_for_project(self._selected_project_id)
        char_count = len(pipes)
        char_line = (
            f"{char_count} character pipeline(s) and all related logs, assets, and jobs."
            if char_count
            else "No character pipelines are registered for this project."
        )
        reply = QMessageBox.warning(
            self,
            "Delete project",
            (
                f"Permanently delete project “{project.name}”?\n\n"
                f"{char_line}\n\n"
                f"Output root (files on disk are not deleted):\n{project.output_root}\n\n"
                "This cannot be undone."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        project_id = self._selected_project_id
        try:
            result = self.controller.delete_project(project_id)
        except ValueError as exc:
            QMessageBox.critical(self, "Delete project", f"Could not delete project:\n{exc}")
            return

        self._selected_pipeline = None
        self._selected_project_id = None
        self._last_log_id = 0
        self._last_drop_path = None
        self._pending_drop_path = None
        self._saved_character_name = None
        self.character_name.clear()
        self.character_slug_label.clear()
        self.project_slug_label.clear()
        self.output_root_label.clear()
        self.unity_path.clear()
        self.save_character_btn.setEnabled(False)
        self.preview_panel.clear_all()
        self._set_unity_prompt_text(self._default_unity_prompt(), saved=True)
        self.stepper.set_stage(StageId.DRAFT.value)
        self.log_viewer.clear()
        self.run_meshy_btn.setEnabled(True)
        self.import_btn.setEnabled(False)
        self._update_download_enabled()
        self.refresh_projects()
        self.status_label.setText(
            f"Deleted project “{result.project_name}” "
            f"({result.pipeline_count} character pipeline(s) removed from database)"
        )

    def _reset_local_database(self) -> None:
        db_path = local_database_path(self.db.db_path if self.db.db_path else None)
        reply = QMessageBox.warning(
            self,
            "Reset local database",
            (
                "This permanently deletes all projects, pipelines, and log entries in:\n\n"
                f"{db_path}\n\n"
                "Output files on disk are not deleted. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            from asset_assembly_automator.workflow.maintenance import reset_application_database

            self.controller.cancel_all_pipelines()
            path, fresh_db = reset_application_database(self.db)
            self.controller.rebind_database(fresh_db)
            self.db = fresh_db
            self.log_viewer.set_database(fresh_db)
            self.log_viewer.clear()
        except OSError as exc:
            QMessageBox.critical(self, "Reset local database", f"Could not reset database:\n{exc}")
            return

        self._selected_pipeline = None
        self._selected_project_id = None
        self._last_log_id = 0
        self._last_drop_path = None
        self._pending_drop_path = None
        self._saved_character_name = None
        self.character_name.clear()
        self.character_slug_label.clear()
        self.save_character_btn.setEnabled(False)
        self.preview_panel.clear_all()
        self.stepper.set_stage(StageId.DRAFT.value)
        self.run_meshy_btn.setEnabled(True)
        self.import_btn.setEnabled(False)
        self._update_download_enabled()
        self.refresh_projects()
        self.status_label.setText(f"Local database reset ({path})")

    def _delete_character(self) -> None:
        if not self._selected_pipeline:
            QMessageBox.information(self, "Delete character", "Select a saved character first.")
            return

        pipe = self.controller.get_pipeline(self._selected_pipeline)
        if not pipe:
            QMessageBox.warning(self, "Delete character", "Character not found in the database.")
            self._refresh_pipeline_list()
            return

        folder = self._resolved_output_folder()
        folder_text = str(folder.resolve()) if folder and folder.exists() else str(folder or "")
        slug = pipeline_character_slug(pipe)
        extra = ""
        if self._is_character_name_dirty():
            extra = "\n\nUnsaved name changes will be discarded."
        reply = QMessageBox.warning(
            self,
            "Delete character",
            (
                f"Permanently delete character “{pipe.asset_name}” ({slug})?\n\n"
                f"Output folder:\n{folder_text}\n\n"
                "This removes all pipeline data from the local database and deletes "
                "the output folder and its contents."
                f"{extra}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        pipeline_id = self._selected_pipeline
        try:
            result = self.controller.delete_character(pipeline_id)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Delete character", f"Could not delete character:\n{exc}")
            return

        self._selected_pipeline = None
        self._last_log_id = 0
        self._last_drop_path = None
        self._pending_drop_path = None
        self._saved_character_name = None
        self.character_name.clear()
        self.character_slug_label.clear()
        self.save_character_btn.setEnabled(False)
        self.preview_panel.clear_all()
        self._set_unity_prompt_text(self._default_unity_prompt(), saved=True)
        self.stepper.set_stage(StageId.DRAFT.value)
        self.log_viewer.clear()
        self.run_meshy_btn.setEnabled(True)
        self._refresh_pipeline_list()
        if result.deleted_output_dirs:
            deleted = "\n".join(str(path) for path in result.deleted_output_dirs)
            self.status_label.setText(f"Deleted character “{result.asset_name}” ({deleted})")
        else:
            self.status_label.setText(
                f"Deleted character “{result.asset_name}” (no output folder on disk)"
            )

    def _delete_output_directory(self) -> None:
        from asset_assembly_automator.workflow.maintenance import (
            delete_output_directory,
            validate_output_delete_path,
        )

        folder = self._resolved_output_folder()
        if folder is None:
            QMessageBox.information(self, "Delete output directory", "Select a project first.")
            return

        error = validate_output_delete_path(folder)
        if error:
            QMessageBox.warning(self, "Delete output directory", error)
            return

        resolved = folder.resolve()
        reply = QMessageBox.warning(
            self,
            "Delete output directory",
            (
                "Permanently delete all files in:\n\n"
                f"{resolved}\n\n"
                "Database records are not removed. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            delete_output_directory(folder)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(
                self, "Delete output directory", f"Could not delete folder:\n{exc}"
            )
            return

        if self._selected_pipeline:
            health = self._refresh_stepper(self._selected_pipeline)
            if health and health.rerun_stage:
                self.status_label.setText(health.message)
            else:
                self.status_label.setText(f"Deleted output directory: {resolved}")
            self._update_import_enabled()
        else:
            self.status_label.setText(f"Deleted output directory: {resolved}")
        self._update_output_folder_display()

    def refresh_projects(self, *, select_project_id: int | None = None) -> None:
        previous_id = select_project_id or self._selected_project_id
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        projects = self.db.list_projects()
        for project in projects:
            self.project_combo.addItem(project.name, project.id)
        self.project_combo.blockSignals(False)

        if not projects:
            self._selected_project_id = None
            self.output_root_label.clear()
            self.project_slug_label.clear()
            self.unity_path.clear()
            self.status_label.setText("Create or select a project to begin.")
            return

        index = 0
        if previous_id is not None:
            idx = self.project_combo.findData(previous_id)
            if idx >= 0:
                index = idx
        self.project_combo.setCurrentIndex(index)
        self._on_project_changed()

    def _new_project(self) -> None:
        from asset_assembly_automator.gui.dialogs.new_project_dialog import NewProjectDialog

        dlg = NewProjectDialog(self.db, self)
        if dlg.exec() != dlg.DialogCode.Accepted or dlg.project_id is None:
            return
        self.refresh_projects(select_project_id=dlg.project_id)
        self.status_label.setText(f"Project created (id {dlg.project_id})")

    def _on_project_changed(self) -> None:
        project_id = self.project_combo.currentData()
        if not project_id:
            self._selected_project_id = None
            self.output_root_label.clear()
            return
        self._selected_project_id = int(project_id)
        project = self.db.get_project(self._selected_project_id)
        if project:
            self.unity_path.setText(project.unity_project_path or "")
            self.project_slug_label.setText(project_output_slug(project))
        self._refresh_pipeline_list()
        self._update_output_folder_display()

    def _on_character_name_changed(self) -> None:
        self._update_character_slug_preview()
        self._update_save_character_state()

    def _is_character_name_dirty(self) -> bool:
        name = self.character_name.text().strip()
        if not name:
            return False
        if self._pending_drop_path:
            return True
        return name != (self._saved_character_name or "")

    def _update_save_character_state(self) -> None:
        self.save_character_btn.setEnabled(self._is_character_name_dirty())

    def _update_character_slug_preview(self) -> None:
        name = self.character_name.text().strip()
        if not name:
            self.character_slug_label.clear()
            return
        self.character_slug_label.setText(character_name_slug(name))
        self._update_output_folder_display()

    def _pipeline_combo_label(self, pipe) -> str:
        slug = pipeline_character_slug(pipe)
        return f"{pipe.asset_name}  ·  {self._friendly_stage_label(pipe)}  ({slug})"

    @staticmethod
    def _friendly_stage_label(pipe) -> str:
        stage_raw = str(pipe.current_stage)
        stage = stage_display_label(stage_raw)
        status = (getattr(pipe, "status", "") or "").lower()
        unity_done, unity_failed = WorkflowWindow._unity_import_state(pipe)
        if unity_done:
            return "Unity imported"
        if unity_failed:
            return "Unity import failed"
        if status == "failed":
            return f"Failed · {stage}"
        if stage_raw == StageId.COMPLETE.value:
            return "Meshy complete"
        if stage_raw == StageId.DRAFT.value:
            return "New · needs T-pose art"
        return stage

    def _resolved_output_folder(self) -> Path | None:
        if not self._selected_project_id:
            return None
        project = self.db.get_project(self._selected_project_id)
        if not project:
            return None
        if self._selected_pipeline:
            pipe = self.db.get_pipeline(self._selected_pipeline)
            if pipe and not self._is_character_name_dirty():
                ensure_pipeline_output_slug(self.db, self._selected_pipeline)
                pipe = self.db.get_pipeline(self._selected_pipeline)
                if pipe:
                    return character_output_root(project, pipe)
        proj_slug = project_output_slug(project)
        char_slug = self.character_slug_label.text().strip()
        if char_slug:
            return Path(project.output_root) / f"{proj_slug}-{char_slug}"
        return Path(project.output_root) / f"{proj_slug}-<character_slug>"

    def _update_output_folder_display(self) -> None:
        folder = self._resolved_output_folder()
        if folder is None:
            self.output_root_label.clear()
            return
        self.output_root_label.setText(str(folder))

    def _browse_output_folder(self) -> None:
        if not self._selected_project_id:
            QMessageBox.information(self, "Output folder", "Select a project first.")
            return
        folder = self._resolved_output_folder()
        if folder is None:
            QMessageBox.information(self, "Output folder", "Select a project first.")
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Output folder", f"Could not create folder:\n{exc}")
            return
        self._update_output_folder_display()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def _refresh_pipeline_list(self, *, select_pipeline_id: int | None = None) -> None:
        if not self._selected_project_id:
            return
        target_id = select_pipeline_id or self._selected_pipeline
        self.pipeline_combo.blockSignals(True)
        self.pipeline_combo.clear()
        pipes = self.db.list_pipelines_for_project(
            self._selected_project_id,
            workflow="meshy_drop",
        )
        for pipe in pipes:
            self.pipeline_combo.addItem(self._pipeline_combo_label(pipe), pipe.id)
        self.pipeline_combo.blockSignals(False)
        if not pipes:
            self._selected_pipeline = None
            self._last_drop_path = None
            self._pending_drop_path = None
            self._saved_character_name = None
            self.pipeline_combo.setCurrentIndex(-1)
            self.character_name.clear()
            self.character_slug_label.clear()
            self.poly_budget.setCurrentText("hero")
            self.stepper.set_stage(StageId.DRAFT.value)
            self._update_save_character_state()
            self._update_output_folder_display()
            self._update_import_enabled()
            self._update_download_enabled()
            self._update_delete_character_enabled()
            return
        index = 0
        if target_id is not None:
            idx = self.pipeline_combo.findData(target_id)
            if idx >= 0:
                index = idx
        self.pipeline_combo.setCurrentIndex(index)
        self._load_pipeline(int(self.pipeline_combo.currentData()))

    def _on_pipeline_selected(self) -> None:
        pipeline_id = self.pipeline_combo.currentData()
        if pipeline_id is None:
            return
        self._load_pipeline(int(pipeline_id))

    def _refresh_stepper(self, pipeline_id: int):
        from asset_assembly_automator.workflow.asset_health import assess_meshy_asset_health

        pipe = self.controller.get_pipeline(pipeline_id)
        if not pipe:
            return None
        health = assess_meshy_asset_health(self.db, pipeline_id)
        unity_done, unity_failed = self._unity_import_state(pipe)
        stepper_kwargs = {
            "unity_import_done": unity_done,
            "unity_import_failed": unity_failed,
        }
        if health.rerun_stage:
            self.stepper.set_stage(
                pipe.current_stage,
                rerun_from=health.rerun_stage.value,
                **stepper_kwargs,
            )
        else:
            self.stepper.set_stage(pipe.current_stage, **stepper_kwargs)
        return health

    @staticmethod
    def _unity_import_state(pipe) -> tuple[bool, bool]:
        result = pipe.metadata.get("unity_import_result")
        if not isinstance(result, dict) or not result:
            return False, False
        if result.get("success"):
            return True, False
        return False, True

    def _load_pipeline(self, pipeline_id: int) -> None:
        pipe = self.controller.get_pipeline(pipeline_id)
        if not pipe:
            return
        self._selected_pipeline = pipeline_id
        self._pending_drop_path = None
        self._saved_character_name = pipe.asset_name
        self.character_name.blockSignals(True)
        self.character_name.setText(pipe.asset_name)
        self.character_name.blockSignals(False)
        self.character_slug_label.setText(pipeline_character_slug(pipe))
        self._update_save_character_state()
        if pipe.poly_budget in ("hero", "npc", "crowd"):
            self.poly_budget.setCurrentText(pipe.poly_budget)
        self.texture_prompt.setPlainText(str(pipe.metadata.get("meshy_texture_prompt") or ""))
        self._set_unity_prompt_from_pipeline(pipe)
        health = self._refresh_stepper(pipeline_id)
        if health and health.rerun_stage:
            self.status_label.setText(health.message)
        else:
            self.status_label.setText(f"Pipeline {pipeline_id} — {pipe.current_stage}")
        self.log_viewer.load_pipeline(pipeline_id, pipe.asset_name)
        self._last_log_id = 0

        image_path = pipe.metadata.get("source_image_path") or pipe.metadata.get("source_drop_path")
        if not image_path:
            tpose = self.db.get_assets(pipeline_id, "tpose")
            if tpose:
                image_path = tpose[0]["file_path"]
        if image_path and Path(str(image_path)).exists():
            self._last_drop_path = str(image_path)
            self.preview_panel.show_tpose_preview(str(image_path))
        else:
            self._last_drop_path = None
            self.preview_panel.clear_tpose_preview()
        self._refresh_mesh_preview(pipeline_id)
        self._update_output_folder_display()
        self._update_import_enabled()
        self._update_download_enabled()
        self._update_delete_character_enabled()

    @staticmethod
    def _stage_at_or_after_meshy_i2d(stage_name: str) -> bool:
        try:
            current = StageId(stage_name)
        except ValueError:
            return False
        i2d_idx = stage_index(StageId.MESHY_I2D)
        current_idx = stage_index(current)
        if i2d_idx < 0 or current_idx < 0:
            return False
        return current_idx >= i2d_idx

    def _refresh_mesh_preview(self, pipeline_id: int | None = None) -> None:
        pid = pipeline_id if pipeline_id is not None else self._selected_pipeline
        if not pid:
            self.preview_panel.clear_mesh_preview()
            return
        pipe = self.controller.get_pipeline(pid)
        if not pipe or not self._stage_at_or_after_meshy_i2d(pipe.current_stage):
            self.preview_panel.clear_mesh_preview()
            return

        meta_path = pipe.metadata.get("mesh_preview_path")
        if meta_path and Path(str(meta_path)).is_file():
            self.preview_panel.show_mesh_preview(str(meta_path))
            return

        from asset_assembly_automator.core.mesh_preview import ensure_mesh_preview

        dirs = get_output_dirs(self.db, pid)
        canonical = dirs["previews"] / Path(str(meta_path)).name if meta_path else None
        if canonical and canonical.is_file():
            self.preview_panel.show_mesh_preview(str(canonical))
            return

        def resolve() -> str | None:
            path = ensure_mesh_preview(pipe, dirs)
            return str(path) if path else None

        future = get_executor().submit(resolve)

        def apply_result(path: str | None) -> None:
            if pid != self._selected_pipeline:
                return
            if path and Path(path).is_file():
                self.preview_panel.show_mesh_preview(path)
            else:
                self.preview_panel.clear_mesh_preview()

        def on_done(done_future) -> None:
            try:
                path = done_future.result()
            except Exception:
                path = None
            QTimer.singleShot(0, lambda: apply_result(path))

        future.add_done_callback(on_done)

    def _meshy_rig_task_id(self, pipeline_id: int) -> str | None:
        pipe = self.controller.get_pipeline(pipeline_id)
        if not pipe:
            return None
        rig_task_id = pipe.metadata.get("rig_task_id")
        if rig_task_id:
            return str(rig_task_id)
        job = self.db.get_external_job(pipeline_id, "rigging", active_only=False)
        return str(job["task_id"]) if job else None

    def _update_download_enabled(self) -> None:
        if not self._selected_pipeline:
            self.download_meshy_btn.setEnabled(False)
            return
        if self._pending_drop_path or self._is_character_name_dirty():
            self.download_meshy_btn.setEnabled(False)
            return
        self.download_meshy_btn.setEnabled(bool(self._meshy_rig_task_id(self._selected_pipeline)))

    def _browse_unity_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select Unity project folder")
        if path and self._selected_project_id:
            self.unity_path.setText(path)
            self.db.update_project(self._selected_project_id, unity_project_path=path)

    def _save_project_settings(self) -> bool:
        if not self._selected_project_id:
            QMessageBox.warning(self, "Project", "Select or create a project first.")
            return False
        unity = self.unity_path.text().strip() or None
        self.db.update_project(self._selected_project_id, unity_project_path=unity)
        return True

    def _new_character(self) -> None:
        from asset_assembly_automator.workflow.bootstrap import (
            create_empty_meshy_pipeline,
            workflow_asset_name_exists,
        )

        if not self._selected_project_id:
            QMessageBox.warning(self, "New character", "Select or create a project first.")
            return

        name, ok = QInputDialog.getText(
            self,
            "New character",
            "Character name (slugged for folders):",
        )
        if not ok:
            return
        asset_name = name.strip()
        if not asset_name:
            QMessageBox.warning(self, "New character", "Enter a character name.")
            return
        if workflow_asset_name_exists(self.db, self._selected_project_id, asset_name):
            QMessageBox.warning(
                self,
                "New character",
                f"A character named “{asset_name}” already exists in this project.",
            )
            return

        try:
            pipeline_id = create_empty_meshy_pipeline(
                self.db,
                self._selected_project_id,
                asset_name,
                poly_budget=self.poly_budget.currentText(),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "New character", f"Could not create character:\n{exc}")
            return

        self._pending_drop_path = None
        self._last_drop_path = None
        self.preview_panel.clear_all()
        self._refresh_pipeline_list(select_pipeline_id=pipeline_id)
        self.status_label.setText(
            f"Created character “{asset_name}” — drop T-pose art, then Save / Run Meshy"
        )

    def _save_character_name(self) -> None:
        if not self._selected_project_id:
            QMessageBox.warning(self, "Character name", "Select a project first.")
            return

        asset_name = self.character_name.text().strip()
        if not asset_name:
            QMessageBox.warning(self, "Character name", "Enter a character name.")
            return

        if self._pending_drop_path:
            from asset_assembly_automator.workflow.bootstrap import (
                bootstrap_meshy_pipeline,
                find_workflow_pipeline,
            )

            try:
                pipeline_id = bootstrap_meshy_pipeline(
                    self.db,
                    self._selected_project_id,
                    asset_name,
                    self._pending_drop_path,
                    poly_budget=self.poly_budget.currentText(),
                    texture_prompt=self.texture_prompt.toPlainText().strip(),
                    existing_pipeline_id=(
                        self._selected_pipeline
                        or find_workflow_pipeline(self.db, self._selected_project_id, asset_name)
                    ),
                    **self._magnific_save_kwargs(),
                )
            except OSError as exc:
                QMessageBox.warning(self, "Save character", f"Could not save dropped image: {exc}")
                return

            self._pending_drop_path = None
            self._pending_already_uprezzed = False
            self._last_drop_path = None
            pipe = self.db.get_pipeline(pipeline_id)
            if pipe:
                source = pipe.metadata.get("source_image_path")
                if source:
                    self._last_drop_path = str(source)
            self._saved_character_name = asset_name
            self._update_save_character_state()
            self._refresh_pipeline_list(select_pipeline_id=pipeline_id)
            self._update_output_folder_display()
            self.status_label.setText(
                f"Saved character “{asset_name}” — preview approved. "
                "Run Meshy to Magnific-uprez (if enabled), then image-to-3D."
            )
            return

        if not self._selected_pipeline:
            QMessageBox.warning(
                self,
                "Character name",
                "Drop a T-pose image first, or select an existing character to rename.",
            )
            return

        pipe = self.controller.get_pipeline(self._selected_pipeline)
        if not pipe:
            return

        if pipe.asset_name == asset_name and not self._is_character_name_dirty():
            return

        self.db.update_pipeline_asset_name(self._selected_pipeline, asset_name)
        ensure_pipeline_output_slug(self.db, self._selected_pipeline)
        pipe = self.controller.get_pipeline(self._selected_pipeline)
        if pipe:
            self.db.update_pipeline_stage(
                self._selected_pipeline,
                pipe.current_stage,
                metadata={
                    **pipe.metadata,
                    "meshy_texture_prompt": self.texture_prompt.toPlainText().strip(),
                },
            )
            self.character_slug_label.setText(pipeline_character_slug(pipe))

        self._saved_character_name = asset_name
        self._update_save_character_state()
        self._refresh_pipeline_list(select_pipeline_id=self._selected_pipeline)
        self._update_output_folder_display()
        self.status_label.setText(f"Renamed character to “{asset_name}”")

    def _magnific_save_kwargs(self) -> dict:
        from asset_assembly_automator.core.config import get_settings

        settings = get_settings()
        return {
            "magnific_enabled": settings.magnific.default_enabled,
            "magnific_upscale_mode": str(self.uprez_mode.currentData()),
            "magnific_upscale_scale_factor": str(self.uprez_scale.currentData()),
            "magnific_upscale_flavor": str(self.uprez_flavor.currentData()),
            "magnific_already_applied": self._pending_already_uprezzed,
        }

    def _apply_magnific_ui_defaults(self) -> None:
        from asset_assembly_automator.core.config import get_settings

        settings = get_settings()
        mode = settings.magnific.upscale_mode
        mode_idx = self.uprez_mode.findData(mode)
        if mode_idx >= 0:
            self.uprez_mode.setCurrentIndex(mode_idx)
        scale_idx = self.uprez_scale.findData(settings.magnific.upscale_scale_factor)
        if scale_idx >= 0:
            self.uprez_scale.setCurrentIndex(scale_idx)
        flavor_idx = self.uprez_flavor.findData(settings.magnific.upscale_flavor)
        if flavor_idx >= 0:
            self.uprez_flavor.setCurrentIndex(flavor_idx)
        self._on_uprez_mode_changed()

    def _on_uprez_mode_changed(self) -> None:
        is_precision = self.uprez_mode.currentData() == "precision_v2"
        self.uprez_flavor.setEnabled(is_precision)
        self.uprez_flavor.setVisible(is_precision)

    def _concept_staging_dir(self) -> Path:
        if self._selected_pipeline:
            return get_output_dirs(self.db, self._selected_pipeline)["concept"]
        if self._selected_project_id:
            project = self.db.get_project(self._selected_project_id)
            if project and project.output_root:
                root = Path(project.output_root) / "Characters" / "_concept_staging"
                root.mkdir(parents=True, exist_ok=True)
                return root
        staging = Path(local_database_path()).parent / "concept_staging"
        staging.mkdir(parents=True, exist_ok=True)
        return staging

    def _current_concept_source_path(self) -> str | None:
        if self._pending_drop_path and Path(self._pending_drop_path).is_file():
            return self._pending_drop_path
        if self._selected_pipeline:
            assets = self.db.get_assets(self._selected_pipeline, "tpose")
            if assets:
                path = assets[0].get("file_path")
                if path and Path(path).is_file():
                    return str(path)
        return None

    def _set_concept_buttons_enabled(self, enabled: bool) -> None:
        for widget in (
            self.use_higgs_btn,
            self.use_magnific_btn,
            self.uprez_btn,
            self.uprez_mode,
            self.uprez_scale,
            self.uprez_flavor,
        ):
            widget.setEnabled(enabled)

    def _apply_concept_result(self, path: str, *, status: str) -> None:
        self._pending_drop_path = str(Path(path).resolve())
        self._pending_already_uprezzed = False
        self.preview_panel.show_tpose_preview(self._pending_drop_path)
        self._update_save_character_state()
        self._update_output_folder_display()
        self.status_label.setText(status)

    def _confirm_provider_cost(
        self,
        *,
        title: str,
        action: str,
        cost_line: str,
    ) -> bool:
        if self.dry_run:
            return True
        from asset_assembly_automator.gui.dialogs.provider_cost_dialog import (
            ProviderCostConfirmDialog,
        )

        asset_name = self.character_name.text().strip() or "character"
        dlg = ProviderCostConfirmDialog(
            self,
            title=title,
            action=action,
            asset_name=asset_name,
            cost_line=cost_line,
        )
        return dlg.exec() == dlg.DialogCode.Accepted

    def _on_use_higgs(self) -> None:
        if not self._selected_project_id:
            QMessageBox.warning(self, "Concept Image", "Select a project first.")
            return
        prompt = self.concept_prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Concept Image", "Enter a concept prompt.")
            return
        from asset_assembly_automator.gui.dialogs.provider_cost_dialog import (
            estimate_higgsfield_generate_cost,
        )

        if not self._confirm_provider_cost(
            title="Confirm Higgsfield generation",
            action="Generate concept image with Higgsfield",
            cost_line=estimate_higgsfield_generate_cost(),
        ):
            return
        self._set_concept_buttons_enabled(False)
        self.loop.create_task(self._run_higgs_concept(prompt))

    def _on_use_magnific(self) -> None:
        if not self._selected_project_id:
            QMessageBox.warning(self, "Concept Image", "Select a project first.")
            return
        prompt = self.concept_prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Concept Image", "Enter a concept prompt.")
            return
        from asset_assembly_automator.core.config import get_settings
        from asset_assembly_automator.gui.dialogs.provider_cost_dialog import (
            estimate_magnific_mystic_cost,
        )

        settings = get_settings()
        if not self._confirm_provider_cost(
            title="Confirm Magnific generation",
            action="Generate concept image with Magnific Mystic",
            cost_line=estimate_magnific_mystic_cost(resolution=settings.magnific.resolution),
        ):
            return
        self._set_concept_buttons_enabled(False)
        self.loop.create_task(self._run_magnific_concept(prompt))

    def _on_uprez(self) -> None:
        if not self._selected_project_id:
            QMessageBox.warning(self, "Concept Image", "Select a project first.")
            return
        source = self._current_concept_source_path()
        if not source:
            QMessageBox.warning(
                self,
                "Uprez",
                "No concept image in preview. Generate, drop, or select a saved character first.",
            )
            return
        from asset_assembly_automator.gui.dialogs.provider_cost_dialog import (
            estimate_magnific_upscale_cost,
        )

        mode = str(self.uprez_mode.currentData())
        scale = str(self.uprez_scale.currentData())
        if not self._confirm_provider_cost(
            title="Confirm Magnific Uprez",
            action="Upscale preview image with Magnific",
            cost_line=estimate_magnific_upscale_cost(scale_factor=scale, mode=mode),
        ):
            return
        self._set_concept_buttons_enabled(False)
        self.loop.create_task(self._run_uprez(source))

    async def _run_higgs_concept(self, prompt: str) -> None:
        from asset_assembly_automator.stages._base import get_higgsfield_client

        client = get_higgsfield_client(self.dry_run, self._concept_staging_dir())
        try:
            result = await client.generate_image(prompt, count=1)
            items = result.get("results") or []
            if not items:
                raise RuntimeError("Higgsfield returned no images")
            path = items[0].get("local_path")
            if not path:
                raise RuntimeError("Higgsfield result missing local_path")
            self._apply_concept_result(
                path,
                status="Higgsfield concept ready — preview, then Save to approve. Magnific uprez runs after approval.",
            )
        except Exception as exc:
            self.status_label.setText(f"Higgsfield failed: {exc}")
            QMessageBox.warning(self, "Use Higgs", str(exc))
        finally:
            self._set_concept_buttons_enabled(True)
            if hasattr(client, "close"):
                await client.close()

    async def _run_magnific_concept(self, prompt: str) -> None:
        from asset_assembly_automator.stages._base import get_magnific_client

        client = get_magnific_client(self.dry_run, self._concept_staging_dir())
        try:
            result = await client.generate_image(prompt)
            items = result.get("results") or []
            if not items:
                raise RuntimeError("Magnific returned no images")
            path = items[0].get("local_path")
            if not path:
                raise RuntimeError("Magnific result missing local_path")
            self._apply_concept_result(
                path,
                status="Magnific concept ready — preview, then Save to approve. Magnific uprez runs after approval.",
            )
        except Exception as exc:
            self.status_label.setText(f"Magnific failed: {exc}")
            QMessageBox.warning(self, "Use Magnific", str(exc))
        finally:
            self._set_concept_buttons_enabled(True)
            if hasattr(client, "close"):
                await client.close()

    async def _run_uprez(self, source: str) -> None:
        from asset_assembly_automator.stages._base import get_magnific_client

        client = get_magnific_client(self.dry_run, self._concept_staging_dir())
        mode = str(self.uprez_mode.currentData())
        scale = str(self.uprez_scale.currentData())
        flavor = str(self.uprez_flavor.currentData()) if mode == "precision_v2" else None
        prompt = self.concept_prompt.toPlainText().strip() if mode == "creative" else None
        try:
            result = await client.upscale_image(
                source,
                scale_factor=scale,
                mode=mode,  # type: ignore[arg-type]
                flavor=flavor,
                prompt=prompt,
            )
            path = result.get("local_path")
            if not path:
                raise RuntimeError("Magnific upscale missing local_path")
            self._apply_concept_result(
                path,
                status=f"Uprez preview ({scale}, {mode}) — Save to approve. Auto-uprez will skip if you keep this image.",
            )
            self._pending_already_uprezzed = True
        except Exception as exc:
            self.status_label.setText(f"Uprez failed: {exc}")
            QMessageBox.warning(self, "Uprez", str(exc))
        finally:
            self._set_concept_buttons_enabled(True)
            if hasattr(client, "close"):
                await client.close()

    def _on_files_dropped(self, paths: list[str]) -> None:
        if not paths:
            return
        if not self._selected_project_id:
            QMessageBox.warning(self, "Project", "Select a project before dropping files.")
            return
        path = Path(paths[0])
        self._pending_drop_path = str(path.resolve())
        self._pending_already_uprezzed = False

        existing_name = self.character_name.text().strip()
        if existing_name:
            self._update_character_slug_preview()
            self._update_save_character_state()
            self._update_output_folder_display()
            self._update_import_enabled()
            self.status_label.setText(
                f"Image dropped — click Save to attach T-pose art to “{existing_name}”"
            )
            return

        default_name = display_name_from_filename(path.stem)
        self._selected_pipeline = None
        self._saved_character_name = None
        self.pipeline_combo.blockSignals(True)
        self.pipeline_combo.setCurrentIndex(-1)
        self.pipeline_combo.blockSignals(False)
        self.character_name.setText(default_name)
        self._update_character_slug_preview()
        self._update_save_character_state()
        self.stepper.set_stage(StageId.DRAFT.value)
        self.log_viewer.clear()
        self._update_output_folder_display()
        self._update_import_enabled()
        self.status_label.setText("Image dropped — edit name if needed, then click Save")

    def _ensure_pipeline(self) -> int | None:
        if not self._selected_project_id:
            QMessageBox.warning(self, "Project", "Select a project first.")
            return None
        if self._pending_drop_path or self._is_character_name_dirty():
            QMessageBox.warning(
                self,
                "Character name",
                "Save the character name before running Meshy.",
            )
            return None
        asset_name = self.character_name.text().strip()
        if not asset_name:
            QMessageBox.warning(self, "Character name", "Enter a character name.")
            return None
        if self._selected_pipeline:
            pipe = self.controller.get_pipeline(self._selected_pipeline)
            if pipe:
                from asset_assembly_automator.workflow.bootstrap import meshy_workflow_start_stage

                mag = self._magnific_save_kwargs()
                meta = {
                    **pipe.metadata,
                    "meshy_texture_prompt": self.texture_prompt.toPlainText().strip(),
                    "magnific_enabled": mag["magnific_enabled"],
                    "magnific_upscale_mode": mag["magnific_upscale_mode"],
                    "magnific_upscale_scale_factor": mag["magnific_upscale_scale_factor"],
                    "magnific_upscale_flavor": mag["magnific_upscale_flavor"],
                }
                current = StageId(pipe.current_stage)
                if current in (StageId.DRAFT, StageId.IMAGE_PREP, StageId.MAGNIFIC_UPREZ):
                    current = meshy_workflow_start_stage(meta)
                self.db.update_pipeline_poly_budget(
                    self._selected_pipeline, self.poly_budget.currentText()
                )
                self.db.update_pipeline_stage(self._selected_pipeline, current.value, metadata=meta)
                return self._selected_pipeline

        QMessageBox.warning(
            self,
            "Character",
            "Drop a T-pose image, save the character name, then run Meshy.",
        )
        return None

    def _run_meshy(self) -> None:
        from asset_assembly_automator.gui.dialogs.meshy_cost_dialog import MeshyCostConfirmDialog

        pipeline_id = self._ensure_pipeline()
        if not pipeline_id:
            return
        dlg = MeshyCostConfirmDialog(
            self,
            asset_name=self.character_name.text().strip(),
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        self.controller.schedule_meshy_workflow(pipeline_id, self.loop)
        self.run_meshy_btn.setEnabled(False)
        self.download_meshy_btn.setEnabled(False)
        self.import_btn.setEnabled(False)

    def _download_from_meshy(self) -> None:
        pipeline_id = self._ensure_pipeline()
        if not pipeline_id:
            return
        if not self._meshy_rig_task_id(pipeline_id):
            QMessageBox.warning(
                self,
                "Download from Meshy",
                "No Meshy rig task found. Run the full Meshy pipeline first.",
            )
            return
        from asset_assembly_automator.core.config import get_settings

        include_basic = get_settings().meshy.include_basic_animations_in_package
        walk_run = (
            "Downloads rig FBX plus walk/run locomotion clips into Source/."
            if include_basic
            else "Warning: meshy.include_basic_animations_in_package is false in config."
        )
        reply = QMessageBox.question(
            self,
            "Download from Meshy",
            (
                f"Re-download the Meshy export package for “{self.character_name.text().strip()}” "
                "from the existing rig task?\n\n"
                "This uses 0 Meshy credits (no new i2d/remesh/rig jobs).\n"
                f"{walk_run}\n\n"
                "Runs: download → QC → package export."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.controller.schedule_meshy_redownload(pipeline_id, self.loop)
        self.run_meshy_btn.setEnabled(False)
        self.download_meshy_btn.setEnabled(False)
        self.import_btn.setEnabled(False)

    def _import_unity(self) -> None:
        if not self._selected_pipeline:
            QMessageBox.warning(self, "Pipeline", "Run Meshy first or drop an image.")
            return
        if self._pending_drop_path or self._is_character_name_dirty():
            QMessageBox.warning(
                self,
                "Character name",
                "Save the character name before importing to Unity.",
            )
            return
        if not self._save_project_settings():
            return
        if not self.unity_path.text().strip():
            QMessageBox.warning(self, "Unity path", "Set the Unity project path before importing.")
            return
        pipe = self.controller.get_pipeline(self._selected_pipeline)
        if pipe and pipe.current_stage != StageId.COMPLETE.value:
            reply = QMessageBox.question(
                self,
                "Meshy incomplete",
                "Meshy pipeline is not complete. Import staged files anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        if self._is_unity_prompt_dirty():
            QMessageBox.warning(
                self,
                "Unity import prompt",
                "Save the Unity import prompt before importing (placeholders are expanded at run time).",
            )
            return
        self.controller.schedule_unity_import(self._selected_pipeline, self.loop)
        self.import_btn.setEnabled(False)

    def _cleanup_unity(self) -> None:
        if not self._selected_pipeline:
            return
        if self._pending_drop_path or self._is_character_name_dirty():
            QMessageBox.warning(
                self,
                "Character name",
                "Save the character name before removing Unity assets.",
            )
            return
        if not self._save_project_settings():
            return
        if not self.unity_path.text().strip():
            QMessageBox.warning(
                self,
                "Unity path",
                "Set the Unity project path before removing Unity assets.",
            )
            return
        pipe = self.controller.get_pipeline(self._selected_pipeline)
        slug = pipeline_character_slug(pipe) if pipe else "this character"
        reply = QMessageBox.warning(
            self,
            "Remove from Unity",
            (
                f"Remove all Unity assets and scene objects for '{slug}'?\n\n"
                "This runs Cursor CLI + Unity MCP and deletes "
                f"Assets/Characters/{slug}/ and PF_{slug} from the Unity project."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.controller.schedule_unity_cleanup(self._selected_pipeline, self.loop)
        self.import_btn.setEnabled(False)
        self.cleanup_unity_btn.setEnabled(False)
        self.status_label.setText("Removing from Unity via Cursor CLI + Unity MCP…")

    def _default_unity_prompt(self) -> str:
        from asset_assembly_automator.workflow.templates import load_unity_import_template

        return load_unity_import_template()

    def _set_unity_prompt_text(self, text: str, *, saved: bool) -> None:
        self.unity_prompt.blockSignals(True)
        self.unity_prompt.setPlainText(text)
        self.unity_prompt.blockSignals(False)
        if saved:
            self._saved_unity_prompt = text
        self._update_save_unity_prompt_state()

    def _set_unity_prompt_from_pipeline(self, pipe) -> None:
        saved = pipe.metadata.get("unity_import_instructions")
        if isinstance(saved, str) and saved.strip():
            self._set_unity_prompt_text(saved, saved=True)
        else:
            self._set_unity_prompt_text(self._default_unity_prompt(), saved=True)

    def _on_unity_prompt_changed(self) -> None:
        self._update_save_unity_prompt_state()

    def _is_unity_prompt_dirty(self) -> bool:
        if self._saved_unity_prompt is None:
            return bool(self.unity_prompt.toPlainText() != self._default_unity_prompt())
        return self.unity_prompt.toPlainText() != self._saved_unity_prompt

    def _update_save_unity_prompt_state(self) -> None:
        dirty = self._is_unity_prompt_dirty()
        self.save_unity_prompt_btn.setEnabled(self._selected_pipeline is not None and dirty)

    def _save_unity_prompt(self) -> None:
        if not self._selected_pipeline:
            QMessageBox.warning(self, "Unity import prompt", "Select a character first.")
            return
        text = self.unity_prompt.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "Unity import prompt", "Prompt cannot be empty.")
            return
        self.controller.save_unity_import_instructions(self._selected_pipeline, text)
        self._saved_unity_prompt = self.unity_prompt.toPlainText()
        self._update_save_unity_prompt_state()
        self.status_label.setText("Saved Unity import prompt for this character")

    def _reset_unity_prompt(self) -> None:
        self._set_unity_prompt_text(self._default_unity_prompt(), saved=False)

    def _cancel(self) -> None:
        if self._selected_pipeline:
            self.controller.cancel_pipeline(self._selected_pipeline)
        self.run_meshy_btn.setEnabled(True)
        self._update_download_enabled()
        self._update_import_enabled()

    def _update_delete_character_enabled(self) -> None:
        self.delete_character_btn.setEnabled(bool(self._selected_pipeline))

    def _update_import_enabled(self) -> None:
        from asset_assembly_automator.workflow.asset_health import assess_meshy_asset_health

        if not self._selected_pipeline:
            self.import_btn.setEnabled(False)
            self.cleanup_unity_btn.setEnabled(False)
            self._update_delete_character_enabled()
            return
        pipe = self.controller.get_pipeline(self._selected_pipeline)
        if not pipe:
            self.import_btn.setEnabled(False)
            self.cleanup_unity_btn.setEnabled(False)
            self._update_delete_character_enabled()
            return
        stage = StageId(pipe.current_stage)
        health = assess_meshy_asset_health(self.db, self._selected_pipeline)
        has_downloads = bool(pipe.metadata.get("downloaded_paths")) and health.assets_present
        unity_path_set = bool(self.unity_path.text().strip())
        self.import_btn.setEnabled(
            health.assets_present
            and unity_path_set
            and (
                stage in {StageId.COMPLETE, StageId.PACKAGE_EXPORT, StageId.UNITY_IMPORT}
                or has_downloads
            )
        )
        self.cleanup_unity_btn.setEnabled(
            unity_path_set and bool(pipe.metadata.get("character_slug"))
        )
        self._update_delete_character_enabled()

    def _on_progress(self, pipeline_id: int, _pct: int, stage: str) -> None:
        if pipeline_id == self._selected_pipeline:
            self._refresh_stepper(pipeline_id)
            self.status_label.setText(f"Running: {stage}")

    def _on_finished(self, pipeline_id: int, success: bool, message: str) -> None:
        if pipeline_id != self._selected_pipeline:
            return
        self.run_meshy_btn.setEnabled(True)
        self._refresh_pipeline_list(select_pipeline_id=pipeline_id)
        pipe = self.controller.get_pipeline(pipeline_id)
        if pipe:
            health = self._refresh_stepper(pipeline_id)
            if pipe.metadata.get("unity_import_instructions"):
                self._set_unity_prompt_from_pipeline(pipe)
            if health and health.rerun_stage:
                self.status_label.setText(health.message)
            else:
                level = "completed" if success else "failed"
                self.status_label.setText(f"{level}: {message}")
            self._update_download_enabled()
            self._update_import_enabled()
            self._refresh_mesh_preview(pipeline_id)
            return
        level = "completed" if success else "failed"
        self.status_label.setText(f"{level}: {message}")

    def _on_log_entry(self, pipeline_id: int, entry: dict) -> None:
        if pipeline_id == self._selected_pipeline:
            self.log_viewer.append_entry(entry)
            self._last_log_id = max(self._last_log_id, int(entry.get("id", 0)))

    def _on_run_blocked(self, message: str) -> None:
        QMessageBox.information(self, "Run blocked", message)
        self.run_meshy_btn.setEnabled(True)
        self._update_download_enabled()
        self._update_import_enabled()

    def _on_pipeline_updated(self, pipeline_id: int) -> None:
        if pipeline_id == self._selected_pipeline:
            self._update_download_enabled()
            self._update_import_enabled()

    def _poll_logs(self) -> None:
        if not self._selected_pipeline:
            return
        rows = self.controller.fetch_logs_since(self._selected_pipeline, self._last_log_id)
        for row in rows:
            self.log_viewer.append_entry(row)
            self._last_log_id = max(self._last_log_id, int(row.get("id", 0)))
        health = self._refresh_stepper(self._selected_pipeline)
        if health and health.rerun_stage:
            self.status_label.setText(health.message)
            self._update_download_enabled()
            self._update_import_enabled()


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    app = QApplication(sys.argv)
    app.setApplicationName("AAA Meshy Workflow")
    setup_theme(app, load_theme_pref())
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = WorkflowWindow(loop, dry_run=dry_run)
    window.show()
    app.processEvents()
    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
