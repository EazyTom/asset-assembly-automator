"""Cursor CLI client — headless agent for Unity MCP import workflows."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from asset_assembly_automator.core.config import get_settings

OnLineCallback = Callable[[str, str, dict[str, Any]], Awaitable[None] | None]
ProgressCallback = Callable[[str], None]

_TOOL_ARG_KEYS = (
    "action",
    "toolName",
    "server",
    "path",
    "prefab_path",
    "controller_path",
    "clip_path",
    "target",
    "name",
    "command",
    "pattern",
    "search_pattern",
)


def _truncate(text: str, limit: int = 160) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _tool_call_payload(tool_call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(tool_call, dict):
        return "tool", {}
    for key, value in tool_call.items():
        if isinstance(value, dict):
            label = key.replace("ToolCall", "") if key.endswith("ToolCall") else key
            return label, value
    return "tool", tool_call


def _summarize_tool_args(args: dict[str, Any]) -> str:
    if not isinstance(args, dict):
        return _truncate(str(args))
    parts: list[str] = []
    for key in _TOOL_ARG_KEYS:
        value = args.get(key)
        if value not in (None, "", []):
            parts.append(f"{key}={value}")
    nested = args.get("arguments")
    if isinstance(nested, dict):
        for key in _TOOL_ARG_KEYS:
            value = nested.get(key)
            if value not in (None, "", []):
                parts.append(f"{key}={value}")
        code = nested.get("code")
        if code:
            parts.append(f"code={_truncate(str(code), 120)}")
    code = args.get("code")
    if code:
        parts.append(f"code={_truncate(str(code), 120)}")
    if not parts:
        return _truncate(str(args))
    return ", ".join(parts)


def _summarize_tool_result(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return _truncate(str(result))
    if result.get("error"):
        return f"error={_truncate(str(result['error']), 120)}"
    success = result.get("success")
    if isinstance(success, dict):
        message = success.get("message") or success.get("result") or success.get("content")
        if message:
            return _truncate(str(message), 180)
        if success.get("exitCode") is not None:
            return f"exitCode={success.get('exitCode')}"
    data = result.get("data")
    if isinstance(data, dict):
        message = data.get("message") or data.get("result")
        if message:
            return _truncate(str(message), 180)
    return "ok"


def format_stream_event_message(event: dict[str, Any]) -> str | None:
    """Turn a Cursor CLI stream-json event into a concise pipeline log line."""
    event_type = event.get("type")
    if event_type == "system":
        subtype = event.get("subtype") or "init"
        model = event.get("model") or event.get("message")
        if model:
            return f"Cursor agent {subtype} (model={model})"
        return f"Cursor agent {subtype}"

    if event_type == "assistant":
        content = event.get("message", {}).get("content") or event.get("content")
        if isinstance(content, list):
            texts = [
                part.get("text") for part in content if isinstance(part, dict) and part.get("text")
            ]
            if texts:
                return _truncate(" ".join(texts), 220)
        elif isinstance(content, str) and content.strip():
            return _truncate(content, 220)
        return None

    if event_type == "tool_call":
        subtype = event.get("subtype") or "event"
        tool_name, payload = _tool_call_payload(event.get("tool_call") or {})
        if subtype == "started":
            args = payload.get("args") if isinstance(payload, dict) else {}
            detail = _summarize_tool_args(args if isinstance(args, dict) else payload)
            return f"Tool started: {tool_name} — {detail}"
        if subtype == "completed":
            result = payload.get("result") if isinstance(payload, dict) else {}
            detail = _summarize_tool_result(result if isinstance(result, dict) else {})
            return f"Tool finished: {tool_name} — {detail}"
        return f"Tool call: {tool_name} ({subtype})"

    if event_type == "result":
        subtype = event.get("subtype")
        if subtype == "success":
            return "Cursor agent finished successfully"
        if subtype:
            return f"Cursor agent result: {subtype}"
        result_text = event.get("result") or event.get("message")
        if isinstance(result_text, str) and result_text.strip():
            return _truncate(result_text, 220)
        return None

    if event_type in {"connection", "retry"}:
        phase = event.get("phase") or event.get("subtype") or event_type
        return f"Cursor CLI {event_type}: {phase}"

    if event_type == "error":
        message = event.get("message") or event.get("error")
        if message:
            return f"Cursor CLI error: {_truncate(str(message), 180)}"

    return None


def resolve_subprocess_argv(command: str, *args: str) -> list[str]:
    """Build argv for asyncio subprocess; Windows .cmd/.bat need cmd.exe /c."""
    resolved = shutil.which(command) or command
    if sys.platform == "win32" and resolved.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", resolved, *args]
    return [resolved, *args]


def stage_cursor_prompt_file(
    prompt: str,
    *,
    cwd: Path,
    name: str = "cursor_workflow",
    prompt_dir: Path | None = None,
) -> Path:
    """Write a workflow prompt to disk for Cursor CLI @-attachment references."""
    target_dir = prompt_dir if prompt_dir is not None else cwd / ".aaa" / "cursor-prompts"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{name}.md"
    path.write_text(prompt, encoding="utf-8")
    return path


def build_attached_prompt_cli_arg(prompt_file: Path, cwd: Path) -> str:
    """Return a short CLI prompt that attaches ``prompt_file`` via @ mention syntax."""
    try:
        rel = prompt_file.resolve().relative_to(cwd.resolve())
        file_ref = f"@{rel.as_posix()}"
    except ValueError:
        file_ref = f"@{prompt_file.resolve().as_posix()}"
    return (
        f"{file_ref} "
        "Follow the attached markdown workflow exactly. "
        "Use Unity MCP tools as instructed. Do not explore the repo unless required."
    )


def _is_cli_failure_line(line: str) -> bool:
    lowered = line.lower()
    return (
        "command line is too long" in lowered
        or "separator is not found, and chunk exceed the limit" in lowered
    )


class CursorCliClient:
    provider_name = "cursor_cli"

    def __init__(
        self,
        *,
        command: str | None = None,
        model: str | None = None,
        extra_args: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        settings = get_settings().cursor_cli
        self.command = command or settings.command
        self.model = model if model is not None else settings.model
        self.extra_args = list(extra_args if extra_args is not None else settings.extra_args)
        self.timeout_seconds = timeout_seconds or settings.timeout_seconds

    async def health_check(self) -> dict[str, Any]:
        if not get_settings().cursor_cli.enabled:
            return {"available": False, "reason": "cursor_cli.enabled is false in config"}
        resolved = shutil.which(self.command)
        if not resolved:
            return {
                "available": False,
                "reason": f"{self.command} not found on PATH — install Cursor CLI",
            }
        try:
            argv = resolve_subprocess_argv(self.command, "status")
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = (stdout or b"").decode("utf-8", errors="replace").strip()
            if proc.returncode != 0:
                return {
                    "available": False,
                    "reason": f"{self.command} status failed: {output or proc.returncode}",
                }
            return {"available": True, "reason": output or "ok", "command_path": resolved}
        except TimeoutError:
            return {"available": False, "reason": f"{self.command} status timed out"}
        except OSError as exc:
            return {"available": False, "reason": str(exc)}

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
    ) -> dict[str, Any]:
        cwd_path = Path(cwd).resolve() if cwd else Path.cwd().resolve()
        prompt_file = stage_cursor_prompt_file(
            prompt,
            cwd=cwd_path,
            name=prompt_file_name or "cursor_workflow",
            prompt_dir=prompt_dir,
        )
        cli_prompt = build_attached_prompt_cli_arg(prompt_file, cwd_path)

        cmd = resolve_subprocess_argv(
            self.command,
            "-p",
            "--force",
            "--trust",
            "--output-format",
            "stream-json",
            "--stream-partial-output",
        )
        use_model = model or self.model
        if use_model:
            cmd.extend(["--model", use_model])
        cmd.extend(self.extra_args)
        cmd.append(cli_prompt)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        events: list[dict[str, Any]] = []
        final_text_parts: list[str] = []
        deadline = timeout or self.timeout_seconds

        async def _emit(level: str, message: str, **context: Any) -> None:
            if on_line:
                result = on_line(level, message, context)
                if asyncio.iscoroutine(result):
                    await result

        await _emit(
            "info",
            f"Cursor CLI started (timeout={deadline}s, cwd={cwd_path})",
            provider=self.provider_name,
            timeout_seconds=deadline,
            cwd=str(cwd_path),
            prompt_file=str(prompt_file),
            prompt_chars=len(prompt),
            cli_prompt_chars=len(cli_prompt),
        )
        await _emit(
            "info",
            f"Workflow prompt attached: {prompt_file.name} ({len(prompt)} chars)",
            provider=self.provider_name,
            prompt_file=str(prompt_file),
        )

        try:
            assert proc.stdout is not None
            while True:
                try:
                    line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=deadline)
                except TimeoutError as exc:
                    proc.kill()
                    await proc.wait()
                    raise TimeoutError(f"Cursor CLI workflow timed out after {deadline}s") from exc
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    events.append(event)
                except json.JSONDecodeError:
                    level = "error" if _is_cli_failure_line(line) else "info"
                    await _emit(level, line, provider=self.provider_name, raw=True)
                    continue

                message = format_stream_event_message(event)
                if not message:
                    continue
                event_type = event.get("type")
                level = "error" if event_type == "error" else "info"
                if event_type == "tool_call" and event.get("subtype") == "completed":
                    tool_name, payload = _tool_call_payload(event.get("tool_call") or {})
                    result = payload.get("result") if isinstance(payload, dict) else {}
                    if isinstance(result, dict) and result.get("error"):
                        level = "warning"
                if event_type == "assistant":
                    content = event.get("message", {}).get("content") or event.get("content")
                    if isinstance(content, list):
                        for part in content:
                            text = part.get("text") if isinstance(part, dict) else None
                            if text:
                                final_text_parts.append(text)
                    elif isinstance(content, str):
                        final_text_parts.append(content)
                elif event_type == "result":
                    result_text = event.get("result") or event.get("message")
                    if isinstance(result_text, str):
                        final_text_parts.append(result_text)
                await _emit(
                    level,
                    message,
                    provider=self.provider_name,
                    event_type=event_type,
                    subtype=event.get("subtype"),
                )

            returncode = await proc.wait()
        except Exception:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise

        final_text = "\n".join(part for part in final_text_parts if part).strip()
        success = returncode == 0
        return {
            "success": success,
            "final_text": final_text,
            "events": events,
            "returncode": returncode,
            "prompt_file": str(prompt_file),
        }


class FakeCursorCliClient(CursorCliClient):
    async def health_check(self) -> dict[str, Any]:
        return {"available": True, "reason": "dry-run fake cursor CLI"}

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
    ) -> dict[str, Any]:
        is_cleanup = (prompt_file_name or "").startswith(
            "unity_cleanup"
        ) or "Unity cleanup" in prompt
        message = (
            "Fake Cursor CLI: Unity cleanup workflow (dry-run)"
            if is_cleanup
            else "Fake Cursor CLI: Unity MCP import workflow (dry-run)"
        )
        if on_line:
            await on_line(
                "info",
                message,
                {"provider": self.provider_name, "cwd": str(cwd or "")},
            )
        final_text = (
            "SUCCESS\nFake unity cleanup complete (dry-run)"
            if is_cleanup
            else "SUCCESS\nFake unity import complete (dry-run)"
        )
        return {
            "success": True,
            "final_text": final_text,
            "events": [],
            "returncode": 0,
            "prompt_file": prompt_file_name or "",
        }
