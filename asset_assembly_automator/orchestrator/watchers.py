from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from asset_assembly_automator.core.config import get_settings


def _file_stable(path: Path, *, checks: int = 3, interval: float = 0.5) -> bool:
    if not path.exists():
        return False
    last_size = -1
    for _ in range(checks):
        size = path.stat().st_size
        if size == last_size and size > 0:
            return True
        last_size = size
        time.sleep(interval)
    return False


class _StableFileHandler(FileSystemEventHandler):
    def __init__(
        self,
        callback: Callable[[Path], None],
        *,
        patterns: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".zip", ".fbx"),
        debounce: float = 1.5,
    ) -> None:
        self.callback = callback
        self.patterns = patterns
        self.debounce = debounce
        self._pending: dict[str, float] = {}

    def on_created(self, event: Any) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in self.patterns:
            return
        self._pending[str(path)] = time.time()

    def on_modified(self, event: Any) -> None:
        self.on_created(event)

    def flush_ready(self) -> None:
        now = time.time()
        ready = [p for p, ts in list(self._pending.items()) if now - ts >= self.debounce]
        for p in ready:
            path = Path(p)
            if _file_stable(path, checks=get_settings().watchers.stability_checks):
                self.callback(path)
            self._pending.pop(p, None)


class ArtifactWatcher:
    """Watch folders for MJ imports and pipeline artifact outputs."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        on_event: Callable[[str, Path], None],
    ) -> None:
        self.loop = loop
        self.on_event = on_event
        self.observer = Observer()
        self._handlers: list[_StableFileHandler] = []
        self._flush_task: asyncio.Task | None = None

    def _emit(self, kind: str, path: Path) -> None:
        def _safe_emit() -> None:
            try:
                self.on_event(kind, path)
            except RuntimeError:
                pass

        self.loop.call_soon_threadsafe(_safe_emit)

    def watch_import_folder(self, folder: str) -> None:
        path = Path(folder)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        handler = _StableFileHandler(lambda p: self._emit("mj_import", p))
        self.observer.schedule(handler, str(path), recursive=False)
        self._handlers.append(handler)

    def watch_output_dir(self, output_dir: str) -> None:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        handler = _StableFileHandler(lambda p: self._emit("artifact", p))
        self.observer.schedule(handler, str(path), recursive=True)
        self._handlers.append(handler)

    def start(self) -> None:
        self.observer.start()

    async def run_flush_loop(self) -> None:
        while True:
            for h in self._handlers:
                h.flush_ready()
            await asyncio.sleep(0.5)

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join(timeout=5)
