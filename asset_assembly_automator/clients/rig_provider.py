from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RigProvider(Protocol):
    async def rig(
        self,
        input_task_id: str,
        *,
        height_meters: float = 1.7,
    ) -> dict[str, Any]: ...

    async def animate(
        self,
        rig_task_id: str,
        action_id: int,
        *,
        fps: int = 30,
    ) -> dict[str, Any]: ...

    @property
    def provider_name(self) -> str: ...
