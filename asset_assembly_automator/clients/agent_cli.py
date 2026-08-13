"""Unified agent CLI selection (Cursor or Claude) for repair and diagnostics."""

from __future__ import annotations

from typing import Any, Protocol

from asset_assembly_automator.clients.claude_cli_client import ClaudeCliClient, FakeClaudeCliClient
from asset_assembly_automator.clients.cursor_cli_client import CursorCliClient, FakeCursorCliClient
from asset_assembly_automator.core.config import get_settings


class AgentCliProtocol(Protocol):
    provider_name: str

    async def health_check(self) -> dict[str, Any]: ...

    async def run_workflow(
        self,
        prompt: str,
        *,
        cwd: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        on_line: Any | None = None,
        prompt_file_name: str | None = None,
        prompt_dir: Any | None = None,
        mcp_config: str | None = None,
    ) -> dict[str, Any]: ...


def get_agent_cli(*, dry_run: bool = False, db=None) -> AgentCliProtocol:
    settings = get_settings()
    provider = settings.agent_cli.provider
    if db is not None:
        stored = db.get_setting("agent_cli_provider")
        if stored in ("cursor", "claude"):
            provider = stored
    if provider == "claude":
        return FakeClaudeCliClient() if dry_run else ClaudeCliClient()
    return FakeCursorCliClient() if dry_run else CursorCliClient()


def agent_provider_label() -> str:
    settings = get_settings()
    return "Claude CLI" if settings.agent_cli.provider == "claude" else "Cursor CLI"
