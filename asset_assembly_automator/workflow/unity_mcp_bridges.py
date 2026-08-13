"""Unity MCP bridge metadata — AnkleBreaker default; Coplay and Official fallbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from asset_assembly_automator.core.config import get_settings

UnityMcpBridgeId = Literal["anklebreaker", "coplay", "official"]

_BRIDGE_ORDER: tuple[UnityMcpBridgeId, ...] = ("anklebreaker", "coplay", "official")


@dataclass(frozen=True)
class UnityMcpBridge:
    id: UnityMcpBridgeId
    label: str
    mcp_config_key: str
    cursor_server_id: str
    docs_url: str
    execute_code_tool: str
    console_tool: str
    ping_tool: str
    editor_state_tool: str
    execute_menu_tool: str
    asset_list_tool: str
    asset_delete_tool: str
    gameobject_delete_tool: str
    gameobject_info_tool: str
    component_properties_tool: str
    scene_save_tool: str
    play_mode_tool: str
    cleanup_success_note: str

    def facts_lines(self) -> list[str]:
        return [
            f"- MCP bridge (AAA default: AnkleBreaker; configured: **{self.label}**)",
            f"- Cursor server id: **{self.cursor_server_id}** (`.mcp.json` key: `{self.mcp_config_key}`)",
            f"- Execute C#: `{self.execute_code_tool}`",
            f"- Console: `{self.console_tool}`",
            f"- Cleanup succeeds only when `{self.execute_code_tool}` returns a line starting with SUCCESS",
        ]

    def workflow_preamble(self) -> str:
        return (
            f"Use **{self.label}** MCP server **`{self.mcp_config_key}`** "
            f"(Cursor: **`{self.cursor_server_id}`**)."
        )


BRIDGES: dict[UnityMcpBridgeId, UnityMcpBridge] = {
    "anklebreaker": UnityMcpBridge(
        id="anklebreaker",
        label="AnkleBreaker",
        mcp_config_key="unity",
        cursor_server_id="user-unity",
        docs_url="https://github.com/naniknataraj/unity-mcp-server",
        execute_code_tool="unity_execute_code",
        console_tool="unity_console_log",
        ping_tool="unity_editor_ping",
        editor_state_tool="unity_editor_state",
        execute_menu_tool="unity_execute_menu_item",
        asset_list_tool="unity_asset_list",
        asset_delete_tool="unity_asset_delete",
        gameobject_delete_tool="unity_gameobject_delete",
        gameobject_info_tool="unity_gameobject_info",
        component_properties_tool="unity_component_get_properties",
        scene_save_tool="unity_scene_save",
        play_mode_tool="unity_play_mode",
        cleanup_success_note="unity_execute_code",
    ),
    "coplay": UnityMcpBridge(
        id="coplay",
        label="Coplay Unity MCP",
        mcp_config_key="unityMCP",
        cursor_server_id="user-unityMCP",
        docs_url="https://github.com/CoplayDev/unity-mcp",
        execute_code_tool="execute_code",
        console_tool="read_console",
        ping_tool="execute_code",
        editor_state_tool="execute_code",
        execute_menu_tool="execute_menu_item",
        asset_list_tool="manage_asset",
        asset_delete_tool="manage_asset",
        gameobject_delete_tool="manage_gameobject",
        gameobject_info_tool="manage_gameobject",
        component_properties_tool="manage_gameobject",
        scene_save_tool="manage_scene",
        play_mode_tool="manage_editor",
        cleanup_success_note="execute_code",
    ),
    "official": UnityMcpBridge(
        id="official",
        label="Official Unity MCP",
        mcp_config_key="unity-mcp",
        cursor_server_id="user-unity-mcp",
        docs_url="https://docs.unity3d.com/Packages/com.unity.ai.assistant@2.0/manual/unity-mcp-overview.html",
        execute_code_tool="Unity_RunCommand",
        console_tool="Unity_GetConsoleLogs",
        ping_tool="Unity_ManageEditor",
        editor_state_tool="Unity_ManageEditor",
        execute_menu_tool="Unity_ManageMenuItem",
        asset_list_tool="Unity_ListResources",
        asset_delete_tool="Unity_ManageAsset",
        gameobject_delete_tool="Unity_ManageGameObject",
        gameobject_info_tool="Unity_ManageGameObject",
        component_properties_tool="Unity_ManageGameObject",
        scene_save_tool="Unity_ManageScene",
        play_mode_tool="Unity_ManageEditor",
        cleanup_success_note="Unity_RunCommand",
    ),
}


def resolve_unity_mcp_bridge(*, db=None) -> UnityMcpBridge:
    bridge_id: UnityMcpBridgeId = get_settings().unity_mcp.bridge  # type: ignore[assignment]
    if db is not None:
        stored = db.get_setting("unity_mcp_bridge")
        if stored in BRIDGES:
            bridge_id = stored  # type: ignore[assignment]
    return BRIDGES[bridge_id]


def bridge_options_markdown() -> str:
    lines = [
        "| Priority | Bridge | Cursor server id | `.mcp.json` key |",
        "|----------|--------|------------------|-----------------|",
    ]
    labels = {
        "anklebreaker": "**1 — Default**",
        "coplay": "2 — Fallback",
        "official": "3 — Fallback",
    }
    for bridge_id in _BRIDGE_ORDER:
        bridge = BRIDGES[bridge_id]
        lines.append(
            f"| {labels[bridge_id]} | **{bridge.label}** | "
            f"**{bridge.cursor_server_id}** | `{bridge.mcp_config_key}` |"
        )
    return "\n".join(lines)


def bridge_tool_mapping_markdown() -> str:
    lines = [
        "| Task | AnkleBreaker (default) | Coplay | Official |",
        "|------|------------------------|--------|----------|",
        "| Ping / compile wait | `unity_editor_ping`, `unity_editor_state` | "
        "`execute_code` (EditorApplication) | `Unity_ManageEditor` GetState |",
        "| Run C# | `unity_execute_code` | `execute_code` | `Unity_RunCommand` |",
        "| Console | `unity_console_log` | `read_console` | `Unity_GetConsoleLogs` |",
        "| Menu import | `unity_execute_menu_item` | `execute_menu_item` | "
        "`Unity_ManageMenuItem` |",
        "| List assets | `unity_asset_list` | `manage_asset` | `Unity_ListResources` |",
        "| Delete asset | `unity_asset_delete` | `manage_asset` Delete | "
        "`Unity_ManageAsset` Delete |",
        "| Save scene / Play | `unity_scene_save`, `unity_play_mode` | "
        "`manage_scene`, `manage_editor` | `Unity_ManageScene`, `Unity_ManageEditor` Play |",
    ]
    return "\n".join(lines)


def compose_bridge_facts(*, db=None) -> str:
    bridge = resolve_unity_mcp_bridge(db=db)
    header = "## MCP bridge (configured)\n\n" + "\n".join(bridge.facts_lines())
    fallbacks = (
        "\n\n## MCP bridge fallbacks (if configured server unavailable)\n\n"
        + bridge_options_markdown()
        + "\n\n"
        + bridge_tool_mapping_markdown()
        + "\n\nOnly **one** Unity MCP server should be active in Cursor to avoid port/tool conflicts."
    )
    return header + fallbacks
