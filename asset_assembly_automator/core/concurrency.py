"""Pipeline concurrency: Meshy/Magnific semaphores and Unity import lock."""

from __future__ import annotations

import asyncio

from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.state_machine import StageId

_meshy_semaphore: asyncio.Semaphore | None = None
_magnific_semaphore: asyncio.Semaphore | None = None
_unity_import_lock: asyncio.Lock | None = None

MESHY_STAGES = frozenset(
    {
        StageId.MESHY_I2D,
        StageId.MESHY_REMESH,
        StageId.MESHY_RIG,
        StageId.MESHY_ANIMATE,
        StageId.MESHY_DOWNLOAD,
    }
)
MAGNIFIC_STAGES = frozenset({StageId.MAGNIFIC_UPREZ})
UNITY_STAGES = frozenset({StageId.UNITY_IMPORT})


def meshy_semaphore() -> asyncio.Semaphore:
    global _meshy_semaphore
    if _meshy_semaphore is None:
        settings = get_settings()
        limit = max(1, settings.meshy.max_concurrent_jobs)
        _meshy_semaphore = asyncio.Semaphore(limit)
    return _meshy_semaphore


def magnific_semaphore() -> asyncio.Semaphore:
    global _magnific_semaphore
    if _magnific_semaphore is None:
        settings = get_settings()
        limit = max(1, settings.magnific.max_concurrent_jobs)
        _magnific_semaphore = asyncio.Semaphore(limit)
    return _magnific_semaphore


def unity_import_lock() -> asyncio.Lock:
    global _unity_import_lock
    if _unity_import_lock is None:
        _unity_import_lock = asyncio.Lock()
    return _unity_import_lock


def stage_semaphore(stage: StageId) -> asyncio.Semaphore | None:
    if stage in MESHY_STAGES:
        return meshy_semaphore()
    if stage in MAGNIFIC_STAGES:
        return magnific_semaphore()
    return None


def stage_uses_unity_lock(stage: StageId) -> bool:
    return stage in UNITY_STAGES
