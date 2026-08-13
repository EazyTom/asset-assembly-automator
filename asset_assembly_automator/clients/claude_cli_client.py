"""Claude CLI client — repair and diagnostics via MCP flags."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from asset_assembly_automator.clients.cursor_cli_client import (
    OnLineCallback,
    build_attached_prompt_cli_arg,
    stage_cursor_prompt_file,
)
from asset_assembly_automator.core.config import get_settings


class FakeClaudeCliClient:
    provider_name = "claude_cli"

    async def health_check(self) -> dict[str, Any]:
        return {"available": True, "reason": "dry-run"}

    async def run_workflow(
        self,
        prompt: str,
        *,
        cwd: str | Path | None = None,
        model: str | None = None,
        timeout: int | None = None,
        on_line: OnLineCallback | None = None,
        prompt_file_name: str | None = None,
        prompt_dir: Path | None = None,
        mcp_config: str | None = None,
    ) -> dict[str, Any]:
        if on_line:
            await on_line("info", "Dry-run Claude CLI workflow", provider=self.provider_name)
        return {
            "success": True,
            "returncode": 0,
            "final_text": "Dry-run Claude CLI completed",
            "events": [],
        }


class ClaudeCliClient:
    provider_name = "claude_cli"

    def __init__(
        self,
        *,
        command: str | None = None,
        model: str | None = None,
        extra_args: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        settings = get_settings().agent_cli
        self.command = command or settings.claude_command
        self.model = model if model is not None else settings.claude_model
        self.extra_args = list(extra_args if extra_args is not None else settings.claude_extra_args)
        self.timeout_seconds = timeout_seconds or get_settings().cursor_cli.timeout_seconds

    async def health_check(self) -> dict[str, Any]:
        resolved = shutil.which(self.command)
        if not resolved:
            return {
                "available": False,
                "reason": f"{self.command} not found on PATH",
            }
        return {"available": True, "reason": "ok", "command_path": resolved}

    async def run_workflow(
        self,
        prompt: str,
        *,
        cwd: str | Path | None = None,
        model: str | None = None,
        timeout: int | None = None,
        on_line: OnLineCallback | None = None,
        prompt_file_name: str | None = None,
        prompt_dir: Path | None = None,
        mcp_config: str | None = None,
    ) -> dict[str, Any]:
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        prompt_file = stage_cursor_prompt_file(
            prompt,
            cwd=cwd_path,
            name=prompt_file_name or "claude_workflow",
            prompt_dir=prompt_dir,
        )
        cli_prompt = build_attached_prompt_cli_arg(prompt_file, cwd_path)

        cmd: list[str] = [self.command, "-p"]
        if mcp_config:
            cmd.extend(["--mcp-config", mcp_config])
        use_model = model or self.model
        if use_model:
            cmd.extend(["--model", use_model])
        cmd.extend(self.extra_args)
        cmd.append(cli_prompt)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        deadline = timeout or self.timeout_seconds
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=deadline)
        output = (stdout or b"").decode("utf-8", errors="replace")
        success = proc.returncode == 0
        if on_line:
            level = "info" if success else "error"
            await on_line(level, output[-500:] if output else f"exit {proc.returncode}")
        return {
            "success": success,
            "returncode": proc.returncode,
            "final_text": output.strip(),
            "prompt_file": str(prompt_file),
            "events": [],
        }
