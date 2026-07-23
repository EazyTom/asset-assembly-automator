from __future__ import annotations

import asyncio
import sys

import qasync
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from asset_assembly_automator import __version__
from asset_assembly_automator.core.db.models import Database, local_database_path
from asset_assembly_automator.core.output_paths import get_output_dirs
from asset_assembly_automator.gui.controller import PipelineController
from asset_assembly_automator.gui.dialogs.getting_started import GettingStartedDialog
from asset_assembly_automator.gui.dialogs.new_pipeline_dialog import NewPipelineDialog
from asset_assembly_automator.gui.dialogs.settings_dialog import SettingsDialog
from asset_assembly_automator.gui.dialogs.whats_new import WhatsNewDialog
from asset_assembly_automator.gui.theme.theme import load_theme_pref, setup_theme
from asset_assembly_automator.gui.views.animation_picker_view import AnimationPickerView
from asset_assembly_automator.gui.views.concept_compare_view import ConceptCompareView
from asset_assembly_automator.gui.views.dashboard_view import DashboardView
from asset_assembly_automator.gui.views.focused_wizard_view import FocusedWizardView
from asset_assembly_automator.gui.views.log_viewer import LogViewer
from asset_assembly_automator.gui.views.phase2_stub_view import Phase2StubView
from asset_assembly_automator.gui.views.prompt_builder_view import PromptBuilderView
from asset_assembly_automator.gui.widgets.pipeline_stepper import PipelineStepper
from asset_assembly_automator.orchestrator.watchers import ArtifactWatcher
from asset_assembly_automator.workflow.maintenance import (
    delete_output_directory,
    reset_application_database,
    validate_output_delete_path,
)


class MainWindow(QMainWindow):
    def __init__(self, loop: qasync.QEventLoop) -> None:
        super().__init__()
        self.loop = loop
        self.db = Database()
        self.controller = PipelineController(self.db)
        self.setWindowTitle(f"Asset Assembly Automator v{__version__}")
        self.resize(1280, 820)
        self._selected_pipeline: int | None = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        sidebar = QVBoxLayout()
        sidebar.addWidget(QLabel("Projects / Pipelines"))
        self.pipeline_list = QListWidget()
        self.pipeline_list.currentRowChanged.connect(self._on_select)
        sidebar.addWidget(self.pipeline_list)
        root.addLayout(sidebar, 1)

        center = QSplitter(Qt.Orientation.Horizontal)

        work_split = QSplitter(Qt.Orientation.Vertical)
        self.stack = QStackedWidget()
        self.dashboard = DashboardView()
        self.wizard = FocusedWizardView()
        self.stack.addWidget(self.dashboard)
        self.stack.addWidget(self.wizard)
        work_split.addWidget(self.stack)

        workflow = QTabWidget()
        self.stepper = PipelineStepper()
        stepper_host = QWidget()
        stepper_layout = QVBoxLayout(stepper_host)
        stepper_layout.setContentsMargins(0, 0, 0, 0)
        stepper_layout.addWidget(self.stepper)
        workflow.addTab(stepper_host, "Progress")
        self.prompt_builder = PromptBuilderView()
        self.prompt_builder.promptSaveRequested.connect(self._on_prompt_save)
        workflow.addTab(self.prompt_builder, "Prompts")
        self.concept_compare = ConceptCompareView()
        self.concept_compare.approveRequested.connect(self._on_approve_concept)
        self.concept_compare.refineRequested.connect(self._on_refine_concept)
        workflow.addTab(self.concept_compare, "Concepts")
        workflow.addTab(AnimationPickerView(), "Animations")
        workflow.addTab(Phase2StubView(), "Phase 2")
        work_split.addWidget(workflow)
        work_split.setStretchFactor(0, 2)
        work_split.setStretchFactor(1, 3)
        center.addWidget(work_split)

        self.log_viewer = LogViewer()
        self.log_viewer.set_database(self.db)
        center.addWidget(self.log_viewer)
        center.setStretchFactor(0, 3)
        center.setStretchFactor(1, 2)
        center.setSizes([760, 420])
        root.addWidget(center, 4)

        toolbar = self.addToolBar("Main")
        for label, slot in [
            ("New Pipeline", self._new_pipeline),
            ("Run Next", self._run_pipeline),
            ("Pause", self._pause),
            ("Settings", self._settings),
            ("Getting Started", self._getting_started),
            ("Focused Mode", self._toggle_mode),
        ]:
            act = toolbar.addAction(label)
            act.triggered.connect(slot)

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction("Reset local database…", self._reset_local_database)
        tools_menu.addAction("Delete output directory…", self._delete_output_directory)

        self.controller.pipelineUpdated.connect(lambda _: self.refresh())
        self.controller.stageProgress.connect(self._on_progress)
        self.controller.stageFinished.connect(self._on_finished)
        self.controller.logEntryAdded.connect(self._on_log_entry)
        self.controller.runBlocked.connect(self._on_run_blocked)

        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self._poll_logs)
        self.refresh_timer.start(1500)

        mj_watch = self.db.get_setting("mj_watch_folder", default="") or ""
        self.watcher = ArtifactWatcher(loop, self._on_watch)
        if mj_watch:
            self.watcher.watch_import_folder(mj_watch)
        self.watcher.start()
        self._watcher_flush_timer = QTimer(self)
        self._watcher_flush_timer.timeout.connect(self._flush_watcher_handlers)
        self._watcher_flush_timer.start(500)

        self._maybe_show_onboarding()
        self.refresh()

    def _flush_watcher_handlers(self) -> None:
        for handler in self.watcher._handlers:
            handler.flush_ready()

    def closeEvent(self, event) -> None:
        self._watcher_flush_timer.stop()
        self.watcher.stop()
        super().closeEvent(event)

    def _maybe_show_onboarding(self) -> None:
        qs = QSettings("AssetAssemblyAutomator", "AAA")
        show_gs = self.db.get_setting("show_getting_started", default="true") != "false"
        if show_gs and qs.value("show_getting_started", True, type=bool):
            self._getting_started()
        show_wn = self.db.get_setting("show_whats_new", default="true") != "false"
        last = self.db.get_setting("last_seen_version", default="")
        if show_wn and last != __version__:
            dlg = WhatsNewDialog(self.db, self)
            dlg.exec()

    def refresh(self) -> None:
        pipes = self.controller.list_pipelines()
        self.dashboard.refresh(pipes)
        selected_row = self.pipeline_list.currentRow()
        self.pipeline_list.clear()
        for p in pipes:
            summary = self.db.get_log_summary(p.id)
            count = summary.get("entry_count") or 0
            self.pipeline_list.addItem(
                f"{p.asset_name} [{p.status}] {p.current_stage} ({count} logs)"
            )
        if pipes:
            row = selected_row if 0 <= selected_row < len(pipes) else 0
            self.pipeline_list.setCurrentRow(row)

    def _on_select(self, row: int) -> None:
        pipes = self.controller.list_pipelines()
        if 0 <= row < len(pipes):
            pipe = pipes[row]
            self._selected_pipeline = pipe.id
            self.stepper.set_stage(pipe.current_stage)
            self.wizard.set_pipeline(pipe.asset_name, pipe.current_stage)
            assets = self.db.get_assets(pipe.id, "concept")
            self.concept_compare.load_assets(assets)
            self.prompt_builder.set_pipeline_context(pipe.asset_name, pipe.metadata)
            self.log_viewer.load_pipeline(pipe.id, pipe.asset_name)

    def _on_progress(self, pipeline_id: int, pct: int, stage: str) -> None:
        if pipeline_id == self._selected_pipeline:
            self.stepper.set_stage(stage)

    def _on_finished(self, pipeline_id: int, success: bool, message: str) -> None:
        self.refresh()
        if pipeline_id == self._selected_pipeline:
            assets = self.db.get_assets(pipeline_id, "concept")
            self.concept_compare.load_assets(assets)
            pipe = self.db.get_pipeline(pipeline_id)
            if pipe:
                self.stepper.set_stage(pipe.current_stage)
                self.wizard.set_pipeline(pipe.asset_name, pipe.current_stage)

    def _on_log_entry(self, pipeline_id: int, entry: dict) -> None:
        if pipeline_id == self._selected_pipeline:
            self.log_viewer.append_entry(entry)

    def _poll_logs(self) -> None:
        if self._selected_pipeline is None:
            return
        logs = self.controller.fetch_logs_since(self._selected_pipeline, self.log_viewer.last_id)
        if logs:
            self.log_viewer.append_entries(logs)

    def _on_watch(self, kind: str, path) -> None:
        if self._selected_pipeline:
            self.controller.on_artifact(kind, str(path), pipeline_id=self._selected_pipeline)
        else:
            self.controller.on_artifact(kind, str(path))

    def _on_run_blocked(self, message: str) -> None:
        QMessageBox.information(self, "Run Next", message)

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
        self.refresh()
        QMessageBox.information(self, "Reset local database", f"Database reset complete:\n{path}")

    def _delete_output_directory(self) -> None:
        if not self._selected_pipeline:
            QMessageBox.information(
                self,
                "Delete output directory",
                "Select a pipeline first.",
            )
            return
        try:
            dirs = get_output_dirs(self.db, self._selected_pipeline)
        except ValueError as exc:
            QMessageBox.warning(self, "Delete output directory", str(exc))
            return
        folder = dirs["root"]
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
        QMessageBox.information(
            self,
            "Delete output directory",
            f"Deleted:\n{resolved}",
        )

    def _on_prompt_save(self, provider: str, prompt_text: str, template_vars: dict) -> None:
        if not self._selected_pipeline:
            QMessageBox.warning(self, "No pipeline", "Select a pipeline first.")
            return
        if not self.controller.save_pipeline_prompt(
            self._selected_pipeline,
            provider,
            prompt_text,
            template_vars,
        ):
            QMessageBox.warning(self, "Save prompt", "Prompt text is empty.")
            return
        pipe = self.controller.get_pipeline(self._selected_pipeline)
        if pipe:
            self.stepper.set_stage(pipe.current_stage)

    def _on_approve_concept(self, asset_id: int, provider: str) -> None:
        if not self._selected_pipeline:
            return
        self.controller.schedule_approve_concept(
            self._selected_pipeline,
            self.loop,
            selected_asset_id=asset_id,
            provider=provider,
        )

    def _on_refine_concept(self) -> None:
        if not self._selected_pipeline:
            return
        self.controller.schedule_refine_concept(self._selected_pipeline, self.loop)

    def _new_pipeline(self) -> None:
        dlg = NewPipelineDialog(self.db, self)
        if dlg.exec() and dlg.pipeline_id:
            self.controller.log_event(
                dlg.pipeline_id,
                "info",
                "Pipeline created from GUI",
                stage="draft",
            )
            self.refresh()
            self.pipeline_list.setCurrentRow(0)

    def _run_pipeline(self) -> None:
        if not self._selected_pipeline:
            QMessageBox.warning(self, "No pipeline", "Select a pipeline first.")
            return
        self.controller.schedule_run(self._selected_pipeline, self.loop)

    def _pause(self) -> None:
        if self._selected_pipeline:
            self.controller.cancel_pipeline(self._selected_pipeline)

    def _settings(self) -> None:
        SettingsDialog(self.db, self).exec()

    def _getting_started(self) -> None:
        GettingStartedDialog(self.db, self).exec()

    def _toggle_mode(self) -> None:
        self.stack.setCurrentIndex(1 if self.stack.currentIndex() == 0 else 0)


def main() -> int:
    app = QApplication(sys.argv)
    setup_theme(app, load_theme_pref())
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = MainWindow(loop)
    window.show()
    with loop:
        loop.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
