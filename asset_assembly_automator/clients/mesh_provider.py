from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MeshProvider(Protocol):
    async def image_to_3d(
        self,
        image_path: str,
        *,
        texture_prompt: str | None = None,
        multi_view_paths: list[str] | None = None,
    ) -> dict[str, Any]: ...

    async def remesh(
        self,
        input_task_id: str,
        *,
        target_polycount: int,
        topology: str = "quad",
    ) -> dict[str, Any]: ...

    async def get_task_status(self, task_id: str, task_type: str) -> dict[str, Any]: ...

    async def poll_until_done(
        self,
        task_id: str,
        task_type: str,
        *,
        timeout: float = 600,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]: ...

    async def download_model(
        self,
        task_id: str,
        task_type: str,
        *,
        fmt: str = "fbx",
        save_to: str,
        include_textures: bool = True,
    ) -> dict[str, Any]: ...
