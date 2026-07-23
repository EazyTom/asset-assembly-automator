from __future__ import annotations

import asyncio
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from asset_assembly_automator.core.db.models import Database, StageResult
from asset_assembly_automator.core.state_machine import MANUAL_GATES, StageId, stage_progress


class PipelineController(QObject):
    pipelineUpdated = pyqtSignal(int)
    stageProgress = pyqtSignal(int, int, str)
    stageFinished = pyqtSignal(int, bool, str)
    logEntryAdded = pyqtSignal(int, dict)
    artifactDetected = pyqtSignal(str, str)
    runBlocked = pyqtSignal(str)

    def __init__(self, db: Database | None = None, *, dry_run: bool = False) -> None:
        super().__init__()
        self.db = db or Database()
        self._dry_run = dry_run
        self._runner = None
        self._tasks: dict[int, asyncio.Task] = {}

    @property
    def runner(self):
        if self._runner is None:
            from asset_assembly_automator.orchestrator.runner import PipelineRunner

            self._runner = PipelineRunner(self.db, dry_run=self._dry_run)
        return self._runner

    def list_pipelines(self) -> list[Any]:
        return self.db.list_pipelines()

    def get_pipeline(self, pipeline_id: int):
        return self.db.get_pipeline(pipeline_id)

    def log_event(
        self,
        pipeline_id: int,
        level: str,
        message: str,
        *,
        stage: str | None = None,
        **context: Any,
    ) -> dict[str, Any]:
        ctx = dict(context)
        if stage:
            ctx["stage"] = stage
        log_id = self.db.add_log(pipeline_id, level, message, context=ctx or None)
        row = self.db.get_logs_since(pipeline_id, since_id=log_id - 1)
        entry = (
            row[0] if row else {"id": log_id, "level": level, "message": message, "context": ctx}
        )
        self.logEntryAdded.emit(pipeline_id, entry)
        return entry

    def _track_task(self, pipeline_id: int, task: asyncio.Task) -> None:
        self._tasks[pipeline_id] = task

        def _done(t: asyncio.Task) -> None:
            if self._tasks.get(pipeline_id) is t:
                self._tasks.pop(pipeline_id, None)
            if t.cancelled():
                self.stageFinished.emit(pipeline_id, False, "Cancelled")
                self.pipelineUpdated.emit(pipeline_id)
                return
            exc = t.exception()
            if exc:
                self.log_event(
                    pipeline_id,
                    "error",
                    f"Background task failed: {exc}",
                )

        task.add_done_callback(_done)

    async def _after_stage(self, pipeline_id: int, result: StageResult) -> None:
        level = "info" if result.success else "error"
        self.log_event(
            pipeline_id,
            level,
            result.message or result.error or "Stage finished",
            stage=result.stage,
        )
        self.stageFinished.emit(pipeline_id, result.success, result.message or result.error or "")
        self.pipelineUpdated.emit(pipeline_id)

    async def run_stage(
        self,
        pipeline_id: int,
        stage: StageId,
        *,
        continue_auto: bool = False,
        **kwargs: Any,
    ) -> StageResult:
        pipe = self.db.get_pipeline(pipeline_id)
        if pipe:
            pct = stage_progress(StageId(pipe.current_stage))
            self.stageProgress.emit(pipeline_id, pct, pipe.current_stage)
        result = await self.runner.run_stage(pipeline_id, stage, **kwargs)
        await self._after_stage(pipeline_id, result)
        if continue_auto and result.success:
            pipe = self.db.get_pipeline(pipeline_id)
            if pipe and StageId(pipe.current_stage) not in MANUAL_GATES:
                return await self.run_pipeline(pipeline_id)
        return result

    async def run_pipeline(self, pipeline_id: int, *, manual: bool = False) -> StageResult:
        pipe = self.db.get_pipeline(pipeline_id)
        if pipe:
            pct = stage_progress(StageId(pipe.current_stage))
            self.stageProgress.emit(pipeline_id, pct, pipe.current_stage)
            self.log_event(
                pipeline_id,
                "info",
                f"Pipeline run started at stage {pipe.current_stage}",
                stage=pipe.current_stage,
            )
        result = await self.runner.run_pipeline(pipeline_id, auto=not manual)
        await self._after_stage(pipeline_id, result)
        return result

    def schedule_run(
        self, pipeline_id: int, loop: asyncio.AbstractEventLoop, *, manual: bool = False
    ) -> None:
        if pipeline_id in self._tasks and not self._tasks[pipeline_id].done():
            self.runBlocked.emit("A run is already in progress for this pipeline.")
            return

        pipe = self.db.get_pipeline(pipeline_id)
        if not pipe:
            self.runBlocked.emit("Pipeline not found.")
            return

        stage = StageId(pipe.current_stage)
        if stage in MANUAL_GATES:
            self.runBlocked.emit(
                "Pipeline is waiting for concept review. Approve a concept on the Concepts tab."
            )
            return
        if stage == StageId.COMPLETE:
            self.runBlocked.emit("Pipeline is already complete.")
            return

        async def _wrap() -> None:
            await self.run_pipeline(pipeline_id, manual=manual)

        self._track_task(pipeline_id, loop.create_task(_wrap()))

    def save_pipeline_prompt(
        self,
        pipeline_id: int,
        provider: str,
        prompt_text: str,
        template_vars: dict[str, str] | None = None,
    ) -> bool:
        text = prompt_text.strip()
        if not text:
            return False

        template_ids = {
            "midjourney": "midjourney_character_tpose",
            "higgsfield": "higgsfield_character_tpose",
            "meshy": "meshy_texture",
        }
        meta_keys = {
            "midjourney": "mj_prompt",
            "higgsfield": "hf_prompt",
            "meshy": "meshy_texture_prompt",
        }
        if provider not in template_ids:
            return False

        self.db.save_prompt(
            pipeline_id,
            provider,
            text,
            template_id=template_ids[provider],
            template_vars=template_vars or {},
        )
        pipe = self.db.get_pipeline(pipeline_id)
        if not pipe:
            return False

        meta = {**pipe.metadata, meta_keys[provider]: text}
        if template_vars:
            identity = template_vars.get("identity", "").strip()
            style = template_vars.get("style", "").strip()
            if identity:
                meta["prompt_identity"] = identity
            if style:
                meta["prompt_style"] = style
        stage = pipe.current_stage
        if stage == StageId.DRAFT.value:
            stage = StageId.PROMPT_BUILD.value
        self.db.update_pipeline_stage(pipeline_id, stage, metadata=meta)
        self.log_event(
            pipeline_id,
            "info",
            f"Saved {provider} prompt",
            stage=stage,
            provider=provider,
        )
        self.pipelineUpdated.emit(pipeline_id)
        return True

    def schedule_prompt_build(
        self,
        pipeline_id: int,
        loop: asyncio.AbstractEventLoop,
        template_vars: dict[str, str],
    ) -> None:
        if pipeline_id in self._tasks and not self._tasks[pipeline_id].done():
            self.runBlocked.emit("A run is already in progress for this pipeline.")
            return

        async def _wrap() -> None:
            pipe = self.db.get_pipeline(pipeline_id)
            if pipe and pipe.current_stage == StageId.DRAFT.value:
                self.db.update_pipeline_stage(pipeline_id, StageId.PROMPT_BUILD.value)
            await self.run_stage(
                pipeline_id,
                StageId.PROMPT_BUILD,
                template_vars=template_vars,
            )

        self._track_task(pipeline_id, loop.create_task(_wrap()))

    def schedule_approve_concept(
        self,
        pipeline_id: int,
        loop: asyncio.AbstractEventLoop,
        *,
        selected_asset_id: int,
        provider: str,
    ) -> None:
        if pipeline_id in self._tasks and not self._tasks[pipeline_id].done():
            self.runBlocked.emit("A run is already in progress for this pipeline.")
            return

        async def _wrap() -> None:
            pipe = self.db.get_pipeline(pipeline_id)
            if pipe and pipe.current_stage != StageId.CONCEPT_REVIEW.value:
                self.db.update_pipeline_stage(pipeline_id, StageId.CONCEPT_REVIEW.value)
            result = await self.runner.run_stage(
                pipeline_id,
                StageId.CONCEPT_REVIEW,
                selected_asset_id=selected_asset_id,
                provider=provider,
            )
            await self._after_stage(pipeline_id, result)
            if result.success:
                await self.run_pipeline(pipeline_id)

        self._track_task(pipeline_id, loop.create_task(_wrap()))

    def schedule_refine_concept(self, pipeline_id: int, loop: asyncio.AbstractEventLoop) -> None:
        if pipeline_id in self._tasks and not self._tasks[pipeline_id].done():
            self.runBlocked.emit("A run is already in progress for this pipeline.")
            return

        async def _wrap() -> None:
            self.db.update_pipeline_stage(pipeline_id, StageId.CONCEPT_GENERATE.value)
            await self.run_pipeline(pipeline_id)

        self._track_task(pipeline_id, loop.create_task(_wrap()))

    def schedule_meshy_workflow(self, pipeline_id: int, loop: asyncio.AbstractEventLoop) -> None:
        if pipeline_id in self._tasks and not self._tasks[pipeline_id].done():
            self.runBlocked.emit("A run is already in progress for this pipeline.")
            return

        pipe = self.db.get_pipeline(pipeline_id)
        if not pipe:
            self.runBlocked.emit("Pipeline not found.")
            return

        stage = StageId(pipe.current_stage)
        from asset_assembly_automator.workflow.asset_health import assess_meshy_asset_health

        health = assess_meshy_asset_health(self.db, pipeline_id)
        if health.rerun_stage:
            self.db.update_pipeline_stage(
                pipeline_id,
                health.rerun_stage.value,
                status="active",
            )
            self.log_event(
                pipeline_id,
                "warning",
                health.message,
                missing=health.missing,
                rerun_from=health.rerun_stage.value,
            )
        elif stage == StageId.COMPLETE:
            self.runBlocked.emit("Pipeline is already complete.")
            return
        if stage in MANUAL_GATES:
            self.runBlocked.emit("Pipeline is waiting at a manual gate.")
            return

        if not health.rerun_stage:
            if pipe.status == "failed" and stage in (StageId.MESHY_QC, StageId.PACKAGE_EXPORT):
                self.db.update_pipeline_stage(
                    pipeline_id,
                    StageId.MESHY_DOWNLOAD.value,
                    status="active",
                )
                self.log_event(
                    pipeline_id,
                    "info",
                    "Retrying from meshy_download after export/QC failure",
                )
            elif pipe.status == "failed":
                self.db.update_pipeline_stage(pipeline_id, stage.value, status="active")

        async def _wrap() -> None:
            await self.run_pipeline(pipeline_id)

        self._track_task(pipeline_id, loop.create_task(_wrap()))

    def schedule_meshy_redownload(self, pipeline_id: int, loop: asyncio.AbstractEventLoop) -> None:
        """Re-run meshy_download → QC → package_export using existing Meshy task IDs (0 credits)."""
        if pipeline_id in self._tasks and not self._tasks[pipeline_id].done():
            self.runBlocked.emit("A run is already in progress for this pipeline.")
            return

        pipe = self.db.get_pipeline(pipeline_id)
        if not pipe:
            self.runBlocked.emit("Pipeline not found.")
            return

        rig_task_id = pipe.metadata.get("rig_task_id")
        if not rig_task_id:
            job = self.db.get_external_job(pipeline_id, "rigging", active_only=False)
            rig_task_id = job["task_id"] if job else None
        if not rig_task_id:
            self.runBlocked.emit(
                "No Meshy rig task found for this character. Run the full Meshy pipeline first."
            )
            return

        self.db.update_pipeline_stage(
            pipeline_id,
            StageId.MESHY_DOWNLOAD.value,
            status="active",
        )
        self.log_event(
            pipeline_id,
            "info",
            "Re-downloading Meshy export from existing rig task (no new Meshy jobs)",
            rig_task_id=rig_task_id,
        )

        async def _wrap() -> None:
            await self.run_pipeline(pipeline_id)

        self._track_task(pipeline_id, loop.create_task(_wrap()))

    def schedule_unity_import(
        self,
        pipeline_id: int,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        if pipeline_id in self._tasks and not self._tasks[pipeline_id].done():
            self.runBlocked.emit("A run is already in progress for this pipeline.")
            return

        pipe = self.db.get_pipeline(pipeline_id)
        if not pipe:
            self.runBlocked.emit("Pipeline not found.")
            return

        project = self.db.get_project(pipe.project_id)
        if not project or not project.unity_project_path:
            self.runBlocked.emit("Set a Unity project path before importing.")
            return

        async def _wrap() -> None:
            await self.run_stage(pipeline_id, StageId.UNITY_IMPORT)

        self._track_task(pipeline_id, loop.create_task(_wrap()))

    def save_unity_import_instructions(self, pipeline_id: int, instructions: str) -> None:
        pipe = self.db.get_pipeline(pipeline_id)
        if not pipe:
            raise ValueError(f"Pipeline {pipeline_id} not found")
        meta = {**pipe.metadata, "unity_import_instructions": instructions.strip()}
        self.db.update_pipeline_stage(pipeline_id, pipe.current_stage, metadata=meta)
        self.log_event(
            pipeline_id,
            "info",
            "Saved Unity import prompt template",
            stage=pipe.current_stage,
        )
        self.pipelineUpdated.emit(pipeline_id)

    def schedule_unity_cleanup(
        self,
        pipeline_id: int,
        loop: asyncio.AbstractEventLoop,
        *,
        guidance: str | None = None,
    ) -> None:
        if pipeline_id in self._tasks and not self._tasks[pipeline_id].done():
            self.runBlocked.emit("A run is already in progress for this pipeline.")
            return

        pipe = self.db.get_pipeline(pipeline_id)
        if not pipe:
            self.runBlocked.emit("Pipeline not found.")
            return

        project = self.db.get_project(pipe.project_id)
        if not project or not project.unity_project_path:
            self.runBlocked.emit("Set a Unity project path before removing Unity assets.")
            return

        async def _wrap() -> None:
            from asset_assembly_automator.workflow.unity_mcp_workflow import (
                run_unity_cleanup_workflow,
            )

            self.log_event(
                pipeline_id,
                "info",
                "Starting Cursor CLI Unity cleanup workflow",
                stage="unity_cleanup",
            )

            async def _on_line(level: str, message: str, context: dict[str, Any]) -> None:
                self.log_event(pipeline_id, level, message, stage="unity_cleanup", **context)

            result = await run_unity_cleanup_workflow(
                self.db,
                pipeline_id,
                dry_run=self.runner.dry_run,
                guidance=guidance,
                on_line=_on_line,
            )
            cli_ok = bool(result.get("success"))
            final_text = result.get("final_text") or ""
            workflow_ok = "SUCCESS" in final_text
            success = cli_ok and workflow_ok
            if cli_ok and not workflow_ok:
                msg = (
                    final_text.strip()
                    or "Unity cleanup finished without SUCCESS confirmation from execute_code"
                )
            else:
                msg = final_text or result.get("reason") or "Unity cleanup finished"
            level = "info" if success else "error"
            self.log_event(pipeline_id, level, msg, stage="unity_cleanup")
            meta = {
                **pipe.metadata,
                "unity_cleanup_result": {
                    "success": success,
                    "returncode": result.get("returncode"),
                    "final_text": result.get("final_text"),
                    "reason": result.get("reason"),
                },
            }
            self.db.update_pipeline_stage(pipeline_id, pipe.current_stage, metadata=meta)
            self.stageFinished.emit(pipeline_id, success, msg)
            self.pipelineUpdated.emit(pipeline_id)

        self._track_task(pipeline_id, loop.create_task(_wrap()))

    def cancel_pipeline(self, pipeline_id: int) -> None:
        self.runner.cancel(pipeline_id)
        task = self._tasks.get(pipeline_id)
        if task and not task.done():
            task.cancel()
        pipe = self.db.get_pipeline(pipeline_id)
        self.log_event(
            pipeline_id,
            "warning",
            "Pipeline run cancelled",
            stage=pipe.current_stage if pipe else None,
        )
        self.pipelineUpdated.emit(pipeline_id)

    def delete_character(self, pipeline_id: int):
        """Cancel any run, remove on-disk output, and delete pipeline DB rows."""
        from asset_assembly_automator.workflow.maintenance import delete_character

        self.runner.cancel(pipeline_id)
        task = self._tasks.pop(pipeline_id, None)
        if task and not task.done():
            task.cancel()
        return delete_character(self.db, pipeline_id)

    def delete_project(self, project_id: int):
        """Cancel any runs and delete project plus all associated pipeline DB rows."""
        from asset_assembly_automator.workflow.maintenance import delete_project

        for pipe in self.db.list_pipelines_for_project(project_id):
            self.runner.cancel(pipe.id)
            task = self._tasks.pop(pipe.id, None)
            if task and not task.done():
                task.cancel()
        return delete_project(self.db, project_id)

    def cancel_all_pipelines(self) -> None:
        for pipeline_id in list(self._tasks.keys()):
            self.cancel_pipeline(pipeline_id)

    def rebind_database(self, db: Database) -> None:
        self.cancel_all_pipelines()
        self.db = db
        if self._runner is not None:
            self._runner.db = db

    def fetch_logs_since(self, pipeline_id: int, since_id: int = 0) -> list[dict]:
        return self.db.get_logs_since(pipeline_id, since_id)

    def on_artifact(self, kind: str, path: str, *, pipeline_id: int | None = None) -> None:
        self.artifactDetected.emit(kind, path)
        if pipeline_id is not None:
            self.log_event(
                pipeline_id, "info", f"Artifact detected ({kind}): {path}", stage="watch"
            )
