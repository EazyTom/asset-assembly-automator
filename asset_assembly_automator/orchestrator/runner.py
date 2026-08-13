from __future__ import annotations

import asyncio
import importlib
from typing import Any

from asset_assembly_automator.core.concurrency import (
    stage_semaphore,
    stage_uses_unity_lock,
    unity_import_lock,
)
from asset_assembly_automator.core.db.models import Database, StageResult
from asset_assembly_automator.core.logging import configure_logging
from asset_assembly_automator.core.state_machine import MANUAL_GATES, StageId, runnable_stage
from asset_assembly_automator.orchestrator.resume import STAGE_MODULE_MAP


class PipelineRunner:
    def __init__(
        self,
        db: Database | None = None,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        max_concurrent: int = 4,
    ) -> None:
        self.db = db or Database()
        self.dry_run = dry_run
        self.verbose = verbose
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[int, asyncio.Task] = {}
        self._cancel_events: dict[int, asyncio.Event] = {}

    def cancel(self, pipeline_id: int) -> None:
        ev = self._cancel_events.get(pipeline_id)
        if ev:
            ev.set()
        task = self._tasks.get(pipeline_id)
        if task and not task.done():
            task.cancel()

    async def run_stage(self, pipeline_id: int, stage: StageId, **kwargs: Any) -> StageResult:
        module_path = STAGE_MODULE_MAP.get(stage)
        if not module_path:
            return StageResult(success=False, stage=stage.value, error=f"No module for {stage}")
        module = importlib.import_module(module_path)
        from asset_assembly_automator.stages._base import bind_db, unbind_db

        token = bind_db(self.db)
        try:
            async with self.semaphore:
                provider_sem = stage_semaphore(stage)
                if provider_sem is not None:
                    async with provider_sem:
                        if stage_uses_unity_lock(stage):
                            lock = unity_import_lock()
                            if lock.locked():
                                self._log_queued(pipeline_id, stage)
                            async with lock:
                                return await module.run(
                                    pipeline_id,
                                    dry_run=self.dry_run,
                                    verbose=self.verbose,
                                    **kwargs,
                                )
                        return await module.run(
                            pipeline_id,
                            dry_run=self.dry_run,
                            verbose=self.verbose,
                            **kwargs,
                        )
                if stage_uses_unity_lock(stage):
                    lock = unity_import_lock()
                    if lock.locked():
                        self._log_queued(pipeline_id, stage)
                    async with lock:
                        return await module.run(
                            pipeline_id,
                            dry_run=self.dry_run,
                            verbose=self.verbose,
                            **kwargs,
                        )
                return await module.run(
                    pipeline_id,
                    dry_run=self.dry_run,
                    verbose=self.verbose,
                    **kwargs,
                )
        finally:
            unbind_db(token)

    def _log_queued(self, pipeline_id: int, stage: StageId) -> None:
        self.db.add_log(
            pipeline_id,
            "info",
            "Queued behind Unity import",
            context={"stage": stage.value, "reason": "queued_unity_import"},
        )

    async def run_pipeline(
        self,
        pipeline_id: int,
        *,
        until: StageId | None = None,
        auto: bool = True,
    ) -> StageResult:
        configure_logging(verbose=self.verbose)
        cancel_event = asyncio.Event()
        self._cancel_events[pipeline_id] = cancel_event
        pipe = self.db.get_pipeline(pipeline_id)
        if not pipe:
            return StageResult(success=False, stage="unknown", error="Pipeline not found")

        self.db.add_log(
            pipeline_id,
            "info",
            "Pipeline run started",
            context={"stage": pipe.current_stage, "asset_name": pipe.asset_name},
        )

        current = runnable_stage(StageId(pipe.current_stage))
        if StageId(pipe.current_stage) == StageId.DRAFT:
            self.db.update_pipeline_stage(pipeline_id, current.value)

        last_result = StageResult(success=True, stage=current.value, message="Starting")

        while current != StageId.COMPLETE:
            if until and current == until:
                break
            if current in MANUAL_GATES and auto:
                self.db.add_log(
                    pipeline_id,
                    "info",
                    f"Waiting at manual gate: {current.value}",
                    context={"stage": current.value},
                )
                last_result = StageResult(
                    success=True,
                    stage=current.value,
                    message=f"Waiting at manual gate: {current.value}",
                )
                break
            last_result = await self.run_stage(pipeline_id, current)
            if not last_result.success:
                self.db.update_pipeline_stage(pipeline_id, current.value, status="failed")
                break
            nxt_name = last_result.next_stage
            if not nxt_name:
                break
            current = StageId(nxt_name)
            pipe = self.db.get_pipeline(pipeline_id)
            if pipe and current == StageId.TURNAROUND and not pipe.multi_view:
                current = StageId.MESHY_I2D

        return last_result

    def start_pipeline_task(self, pipeline_id: int, **kwargs: Any) -> asyncio.Task:
        task = asyncio.create_task(self.run_pipeline(pipeline_id, **kwargs))
        self._tasks[pipeline_id] = task
        return task

    async def run_auto_from(self, pipeline_id: int, start: StageId) -> StageResult:
        self.db.update_pipeline_stage(pipeline_id, start.value)
        return await self.run_pipeline(pipeline_id, auto=True)
