from __future__ import annotations

import asyncio
import json
import logging
import webbrowser
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from pydantic import AnyUrl

from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.secrets import get_secret

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"completed", "failed", "canceled", "nsfw", "ip_detected"}
PENDING_STATUSES = {"pending", "waiting", "queued", "in_progress", "ip_detect"}


class JsonFileTokenStorage:
    """Persist Higgsfield MCP OAuth tokens between GUI/CLI sessions."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def _save(self) -> None:
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    async def get_tokens(self) -> OAuthToken | None:
        raw = self._data.get("tokens")
        if not raw:
            return None
        return OAuthToken.model_validate(raw)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._data["tokens"] = tokens.model_dump(mode="json")
        self._save()

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = self._data.get("client_info")
        if not raw:
            return None
        return OAuthClientInformationFull.model_validate(raw)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._data["client_info"] = client_info.model_dump(mode="json")
        self._save()


def _parse_http_request(raw: bytes) -> tuple[str, dict[str, list[str]]]:
    text = raw.decode("utf-8", errors="replace")
    header_block, _, _ = text.partition("\r\n\r\n")
    lines = header_block.split("\r\n")
    request_line = lines[0] if lines else ""
    path = request_line.split(" ")[1] if " " in request_line else "/"
    parsed = urlparse(path)
    return parsed.path, parse_qs(parsed.query)


async def _wait_for_oauth_callback(
    host: str, port: int, path: str, timeout: float
) -> tuple[str, str | None]:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[tuple[str, str | None]] = loop.create_future()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await reader.read(8192)
            req_path, query = _parse_http_request(raw)
            if req_path.rstrip("/") != path.rstrip("/"):
                writer.write(b"HTTP/1.1 404 Not Found\r\n\r\n")
                await writer.drain()
                return
            code = (query.get("code") or [""])[0]
            state = (query.get("state") or [None])[0]
            body = (
                b"<html><body><h2>Higgsfield connected</h2>"
                b"<p>You can close this tab and return to Asset Assembly Automator.</p>"
                b"</body></html>"
            )
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/html; charset=utf-8\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode()
                + body
            )
            await writer.drain()
            if not future.done():
                future.set_result((code, state))
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, host, port)
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    finally:
        server.close()
        await server.wait_closed()


def _tool_payload(result: Any) -> dict[str, Any]:
    if getattr(result, "isError", False):
        parts = []
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        raise RuntimeError(" ".join(parts) or "Higgsfield MCP tool failed")

    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured

    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if not text:
            continue
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return {}


def _normalize_model(model: str) -> str:
    return model.replace("-", "_")


def _parse_redirect_uri(redirect_uri: str) -> tuple[str, int, str]:
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/callback"
    return host, port, path


class HiggsfieldMcpClient:
    """Call Higgsfield hosted MCP (https://mcp.higgsfield.ai/mcp) tools."""

    def __init__(self) -> None:
        settings = get_settings()
        self.mcp_url = settings.higgsfield.mcp_url.rstrip("/")
        self.redirect_uri = settings.higgsfield.oauth_redirect_uri
        self.oauth_timeout = settings.higgsfield.oauth_timeout_seconds
        self.storage = JsonFileTokenStorage(
            settings.paths.app_data / "mcp" / "higgsfield_oauth.json"
        )
        self._http: httpx.AsyncClient | None = None
        self._session: ClientSession | None = None
        self._exit_stack: Any | None = None

    async def _build_http_client(self) -> httpx.AsyncClient:
        bearer = get_secret("HF_MCP_ACCESS_TOKEN") or get_secret("HIGGSFIELD_MCP_TOKEN")
        if bearer:
            return create_mcp_http_client(headers={"Authorization": f"Bearer {bearer}"})

        host, port, path = _parse_redirect_uri(self.redirect_uri)

        async def redirect_handler(url: str) -> None:
            webbrowser.open(url)

        async def callback_handler() -> tuple[str, str | None]:
            return await _wait_for_oauth_callback(host, port, path, self.oauth_timeout)

        oauth = OAuthClientProvider(
            server_url=self.mcp_url,
            client_metadata=OAuthClientMetadata(
                redirect_uris=[AnyUrl(self.redirect_uri)],
                token_endpoint_auth_method="none",
                grant_types=["authorization_code", "refresh_token"],
                response_types=["code"],
                scope="openid email offline_access",
                client_name="Asset Assembly Automator",
            ),
            storage=self.storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
            timeout=float(self.oauth_timeout),
        )
        return create_mcp_http_client(auth=oauth)

    @asynccontextmanager
    async def session(self):
        http = await self._build_http_client()
        async with http:
            async with streamable_http_client(self.mcp_url, http_client=http) as (
                read_stream,
                write_stream,
                _,
            ):
                async with ClientSession(read_stream, write_stream) as mcp_session:
                    await mcp_session.initialize()
                    yield mcp_session

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self.session() as mcp_session:
            result = await mcp_session.call_tool(
                name,
                arguments,
                read_timeout_seconds=timedelta(seconds=180),
            )
            return _tool_payload(result)

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str,
        count: int = 1,
        aspect_ratio: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": _normalize_model(model),
            "prompt": prompt,
            "count": max(1, min(count, 4)),
        }
        if aspect_ratio:
            params["aspect_ratio"] = aspect_ratio

        payload = await self.call_tool("generate_image", {"params": params})
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))

        results = payload.get("results") or []
        if not results and payload.get("generation"):
            results = [payload["generation"]]

        completed: list[dict[str, Any]] = []
        for item in results:
            status = str(item.get("status", "")).lower()
            if status in TERMINAL_STATUSES and status != "completed":
                raise RuntimeError(f"Higgsfield generation failed: {status}")
            if status == "completed":
                completed.append(item)
                continue
            job_id = item.get("id")
            if not job_id:
                continue
            completed.append(await self._poll_job(str(job_id)))

        if not completed:
            raise RuntimeError("Higgsfield MCP returned no image results")

        return {"results": completed[: max(1, count)]}

    async def _poll_job(self, job_id: str) -> dict[str, Any]:
        for _ in range(90):
            payload = await self.call_tool(
                "job_status",
                {"jobId": job_id, "sync": True},
            )
            generation = payload.get("generation") or {}
            status = str(generation.get("status", "")).lower()
            if status == "completed":
                return generation
            if status in TERMINAL_STATUSES:
                raise RuntimeError(f"Higgsfield job {job_id} failed: {status}")
            delay = payload.get("poll_after_seconds")
            if isinstance(delay, (int, float)) and delay > 0:
                await asyncio.sleep(min(float(delay), 10.0))
            else:
                await asyncio.sleep(2)
        raise TimeoutError(f"Higgsfield job {job_id} timed out")

    async def get_cost(self, prompt: str, *, model: str | None = None) -> dict[str, Any]:
        settings = get_settings()
        model_name = _normalize_model(model or settings.higgsfield.default_image_model)
        return await self.call_tool(
            "generate_image",
            {"params": {"model": model_name, "prompt": prompt, "get_cost": True}},
        )
