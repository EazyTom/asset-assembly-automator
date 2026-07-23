"""Phase 2 stub: Blender MCP + Auto-Rig Pro fallback rig provider."""

from __future__ import annotations

from typing import Any


class BlenderArpClient:
    provider_name = "blender_arp"

    async def health_check(self) -> dict[str, Any]:
        return {
            "available": False,
            "reason": (
                "Phase 2 — requires live Blender with ahujasid/blender-mcp and Auto-Rig Pro enabled"
            ),
        }

    async def rig(self, model_path: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Blender ARP rigging is Phase 2")

    async def animate(self, rig_task_id: str, action_id: int, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("Blender ARP animation is Phase 2")
