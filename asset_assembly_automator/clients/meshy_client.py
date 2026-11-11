from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import time
import uuid
import zipfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from asset_assembly_automator.clients.mesh_provider import MeshProvider
from asset_assembly_automator.clients.rig_provider import RigProvider
from asset_assembly_automator.core.secrets import meshy_api_key

ProgressCallback = Callable[[str], None]
SleepFn = Callable[[float], Awaitable[None]]

TERMINAL_STATUSES = frozenset({"SUCCEEDED", "FAILED", "CANCELED"})
TRANSIENT_TASK_ERROR_TYPES = frozenset({"timeout", "service_unavailable", "server_error"})

TASK_ENDPOINTS: dict[str, str] = {
    "image-to-3d": "/openapi/v1/image-to-3d",
    "multi-image-to-3d": "/openapi/v1/multi-image-to-3d",
    "remesh": "/openapi/v1/remesh",
    "retexture": "/openapi/v1/retexture",
    "rigging": "/openapi/v1/rigging",
    "animation": "/openapi/v1/animations",
}

SMART_TOPOLOGY_POLYCOUNT_MAX = {"meshy-t2": 15000, "meshy-t2.5": 30000}
RETEXTURE_PROMPT_MAX_CHARS = 800

# Meshy has no idempotency key, so after an ambiguous create we adopt a task created
# within this window of our request (allowing for client/server clock skew).
_CREATE_RECOVERY_SKEW_MS = 30_000
# Task ids this process created or adopted, so a concurrent pipeline's new task is never
# mistaken for ours during create recovery.
_CLAIMED_TASK_IDS: set[str] = set()


_NO_RETRY_ERROR_CODES = frozenset({"parameter_unknown", "parameter_invalid_value"})
_DOWNLOAD_CONCURRENCY = 4


class MeshyTaskCanceled(asyncio.CancelledError):
    """Local wait stopped. ``deleted`` is true when Meshy accepted DELETE of a PENDING task."""

    def __init__(self, task_id: str, *, deleted: bool) -> None:
        super().__init__(f"Meshy task {task_id} cancelled")
        self.task_id = task_id
        self.deleted = deleted


class MeshyApiError(RuntimeError):
    """Meshy rejected a request. For a create, a 4xx means no task was created."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MeshyTransientError(MeshyApiError):
    """Retryable failure (network, 429, 5xx) that persisted after all attempts."""


class MeshyCreateUncertainError(MeshyApiError):
    """A create request failed after it may have reached Meshy; a charged task may exist."""


class MeshyPollTimeout(TimeoutError):
    """Stopped waiting for a task; the task itself keeps running on Meshy."""

    def __init__(self, task_id: str, status: str, waited_seconds: float) -> None:
        minutes = waited_seconds / 60
        super().__init__(
            f"Meshy task {task_id} still {status} after {minutes:.0f} min. "
            "The task keeps running on Meshy; re-run this stage to reattach to it."
        )
        self.task_id = task_id
        self.status = status


def task_error_info(task: dict[str, Any]) -> dict[str, str]:
    err = task.get("task_error")
    if not isinstance(err, dict):
        return {}
    return {key: str(err[key]) for key in ("type", "code", "message") if err.get(key)}


def is_transient_task_failure(task: dict[str, Any]) -> bool:
    return (
        task.get("status") == "FAILED"
        and task_error_info(task).get("type") in TRANSIENT_TASK_ERROR_TYPES
    )


def describe_task_failure(task: dict[str, Any]) -> str:
    status = str(task.get("status") or "UNKNOWN")
    info = task_error_info(task)
    detail = info.get("message") or info.get("type")
    if not detail:
        return status
    code = info.get("code")
    return f"{status} ({code}): {detail}" if code else f"{status}: {detail}"


def consumed_credits(task: dict[str, Any]) -> float | None:
    raw = task.get("consumed_credits")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _retry_after_seconds(resp: httpx.Response | None, default: float) -> float:
    if resp is None:
        return default
    try:
        return max(0.0, float(resp.headers.get("Retry-After")))
    except (TypeError, ValueError):
        return default


def _backoff_seconds(attempt: int) -> float:
    return min(30.0, 2.0 ** (attempt - 1)) + random.uniform(0, 1)


def _error_body(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error_code(resp: httpx.Response) -> str:
    return str(_error_body(resp).get("code") or "")


def _error_message(resp: httpx.Response) -> str:
    data = _error_body(resp)
    message = str(data.get("message") or "") if data else ""
    code = str(data.get("code") or "") if data else ""
    if code and message:
        return f"{code}: {message}"
    if code or message:
        return code or message
    return resp.text[:300]


def task_output(task: dict[str, Any] | None) -> dict[str, Any]:
    """Where model, texture, and thumbnail URLs live.

    v2 puts them on ``output``. v1 rig and animation use ``result``. v1 image-to-3D,
    remesh, and retexture keep them on the task itself.
    """
    if not isinstance(task, dict):
        return {}
    output = task.get("output")
    if isinstance(output, dict):
        return output
    result = task.get("result")
    if isinstance(result, dict):
        return result
    return task


def normalize_task(task: dict[str, Any] | None) -> dict[str, Any]:
    """Copy non-null asset fields up so callers can keep reading the v1 names."""
    if not isinstance(task, dict):
        return {}
    source = task_output(task)
    if source is task:
        return task
    merged = dict(task)
    for key, value in source.items():
        if value is None:
            continue
        current = merged.get(key)
        if current is None or current in ("", {}, []):
            merged[key] = value
    return merged


def _resolve_api_version(configured: str | None, *, explicit: str | None) -> str:
    if explicit in ("v1", "v2"):
        return explicit
    env = os.environ.get("AAA_MESHY__API_VERSION", "").strip().lower()
    if env in ("v1", "v2"):
        return env
    chosen = str(configured or "v1").strip().lower()
    return chosen if chosen in ("v1", "v2") else "v1"


def _created_at_ms(task: dict[str, Any]) -> int:
    try:
        return int(task.get("created_at") or 0)
    except (TypeError, ValueError):
        return 0


def _basename_from_url(url: str, fallback: str) -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    return name or fallback


def _iter_texture_downloads(texture_urls: Any) -> list[tuple[str, str]]:
    """Return (filename, url) pairs from Meshy texture_urls."""
    downloads: list[tuple[str, str]] = []
    if not texture_urls:
        return downloads
    if isinstance(texture_urls, list):
        for index, entry in enumerate(texture_urls):
            if isinstance(entry, str) and entry:
                downloads.append((f"texture_{index}.png", entry))
            elif isinstance(entry, dict):
                for map_name, url in entry.items():
                    if url and isinstance(url, str):
                        suffix = Path(map_name).suffix or ".png"
                        stem = Path(str(map_name)).stem or f"texture_{index}"
                        downloads.append((f"{stem}{suffix}", url))
    return downloads


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_IEND = b"IEND\xaeB`\x82"
_PBR_TEXTURE_NAMES = ("base_color", "normal", "metallic", "roughness", "ao", "emissive")


def _extract_png_chunks(data: bytes) -> list[bytes]:
    chunks: list[bytes] = []
    start = 0
    while True:
        idx = data.find(_PNG_SIGNATURE, start)
        if idx < 0:
            break
        end = data.find(_PNG_IEND, idx)
        if end < 0:
            break
        end += len(_PNG_IEND)
        chunks.append(data[idx:end])
        start = end
    return chunks


def _texture_filename_for_index(index: int, total: int, ext: str = ".png") -> str:
    if total == 1:
        return f"base_color{ext}"
    if index < len(_PBR_TEXTURE_NAMES):
        return f"{_PBR_TEXTURE_NAMES[index]}{ext}"
    return f"texture_{index}{ext}"


def _extract_textures_from_fbx(fbx_bytes: bytes, textures_dir: Path) -> list[Path]:
    """Extract embedded PNG textures from a Meshy FBX when API texture_urls expired."""
    textures_dir.mkdir(parents=True, exist_ok=True)
    png_chunks = _extract_png_chunks(fbx_bytes)
    saved: list[Path] = []
    total = len(png_chunks)
    for index, chunk in enumerate(png_chunks):
        path = textures_dir / _texture_filename_for_index(index, total)
        path.write_bytes(chunk)
        saved.append(path)
    return saved


def _geometry_resolution(cfg: dict[str, Any], ai_model: str, *, multi_image: bool) -> str:
    value = str(cfg.get("geometry_resolution") or "standard")
    if value == "standard" and cfg.get("ultra_mode"):
        value = "2k"
    if value == "4k" and (multi_image or ai_model not in ("meshy-7.1", "latest")):
        value = "2k"
    return value


class MeshyClient(MeshProvider, RigProvider):
    provider_name = "meshy"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.meshy.ai",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: SleepFn | None = None,
        api_version: str | None = None,
    ) -> None:
        from asset_assembly_automator.core.config import get_settings

        settings = get_settings().meshy
        self.api_key = api_key or meshy_api_key() or ""
        self.base_url = base_url.rstrip("/")
        self.api_version = _resolve_api_version(settings.api_version, explicit=api_version)
        self.max_attempts = max(1, settings.request_max_attempts)
        self.poll_timeout = float(settings.poll_timeout_seconds)
        self.poll_interval = float(settings.poll_interval_seconds)
        self.create_recovery_wait = float(settings.create_recovery_wait_seconds)
        self._transport = transport
        self._sleep: SleepFn = sleep or asyncio.sleep
        self._client: httpx.AsyncClient | None = None
        self._download_client: httpx.AsyncClient | None = None
        self._task_type_overrides: dict[str, str] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=httpx.Timeout(120.0, connect=30.0),
                transport=self._transport,
            )
        return self._client

    async def _get_download_client(self) -> httpx.AsyncClient:
        # Asset URLs are pre-signed CDN links; never send the API key to them.
        if self._download_client is None:
            self._download_client = httpx.AsyncClient(
                timeout=httpx.Timeout(300.0, connect=30.0),
                follow_redirects=True,
                transport=self._transport,
            )
        return self._download_client

    async def close(self) -> None:
        for attr in ("_client", "_download_client"):
            client = getattr(self, attr)
            if client:
                await client.aclose()
                setattr(self, attr, None)

    async def health_check(self) -> dict[str, Any]:
        if not self.api_key:
            return {"available": False, "reason": "MESHY_API_KEY not configured"}
        try:
            path = "/openapi/v2/balance" if self.api_version == "v2" else "/openapi/v1/balance"
            data = await self._get(path)
            return {"available": True, "balance": data}
        except MeshyApiError as exc:
            if exc.status_code == 401:
                return {"available": False, "reason": "Meshy API key rejected (401)"}
            return {"available": False, "reason": str(exc)}
        except Exception as exc:
            return {"available": False, "reason": str(exc)}

    async def _get_response(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        client = await self._get_client()
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            resp: httpx.Response | None = None
            try:
                resp = await client.get(path, params=params, timeout=30.0)
            except httpx.TransportError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code < 400:
                    return resp
                if resp.status_code != 429 and resp.status_code < 500:
                    raise MeshyApiError(
                        f"GET {path} failed ({resp.status_code}): {_error_message(resp)}",
                        status_code=resp.status_code,
                    )
                last_error = f"HTTP {resp.status_code}: {_error_message(resp)}"
            if attempt < self.max_attempts:
                await self._sleep(_retry_after_seconds(resp, _backoff_seconds(attempt)))
        raise MeshyTransientError(
            f"GET {path} failed after {self.max_attempts} attempts ({last_error})"
        )

    async def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return (await self._get_response(path, params=params)).json()

    def _endpoint(self, task_type: str) -> str:
        path = TASK_ENDPOINTS[task_type]
        if self.api_version == "v2":
            return path.replace("/openapi/v1/", "/openapi/v2/", 1)
        return path

    async def _list_recent_tasks(self, create_path: str) -> Any:
        if self.api_version == "v2":
            kind = create_path.rstrip("/").rsplit("/", 1)[-1]
            return await self._get(
                "/openapi/v2/tasks",
                params={"type": kind, "sort_by": "-created_at", "page_size": 10},
            )
        return await self._get(create_path, params={"sort_by": "-created_at", "page_size": 10})

    async def _create(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a task-creating request without risking a duplicate charged task.

        Only failures that prove no task was created are retried (connection never
        established, 429). Timeouts and 5xx are ambiguous: check Meshy's task list
        before creating again, as Meshy's task-lifecycle guidance requires.
        """
        client = await self._get_client()
        started_ms = int(time.time() * 1000)
        retried_after_check = False
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = await client.post(path, json=payload)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                if attempt >= self.max_attempts:
                    raise MeshyApiError(f"Could not reach Meshy for POST {path}: {exc}") from exc
                await self._sleep(_backoff_seconds(attempt))
                continue
            except httpx.TransportError as exc:
                outcome = f"{type(exc).__name__}: {exc}"
            else:
                if _error_code(resp) in _NO_RETRY_ERROR_CODES or (
                    400 <= resp.status_code < 500 and resp.status_code != 429
                ):
                    raise MeshyApiError(
                        f"POST {path} rejected ({resp.status_code}): {_error_message(resp)}",
                        status_code=resp.status_code,
                    )
                if resp.status_code == 429:
                    if attempt >= self.max_attempts:
                        raise MeshyApiError(
                            f"POST {path} rate limited (429): {_error_message(resp)}",
                            status_code=429,
                        )
                    await self._sleep(_retry_after_seconds(resp, _backoff_seconds(attempt)))
                    continue
                if resp.status_code < 400:
                    return self._created_task(path, resp.json())
                outcome = f"HTTP {resp.status_code}: {_error_message(resp)}"

            if retried_after_check:
                raise MeshyCreateUncertainError(
                    f"POST {path} failed again with an unknown outcome ({outcome}). "
                    "Check your Meshy task list before re-running so you are not charged twice."
                )
            recovered = await self._recover_created_task(path, started_ms, outcome)
            if recovered is not None:
                return recovered
            retried_after_check = True
            started_ms = int(time.time() * 1000)

    @staticmethod
    def _created_task(path: str, data: Any) -> dict[str, Any]:
        task_id = ""
        status = "PENDING"
        if isinstance(data, dict):
            if isinstance(data.get("id"), str) and data["id"]:
                task_id = data["id"]
                status = str(data.get("status") or "PENDING")
            elif isinstance(data.get("result"), str) and data["result"]:
                task_id = data["result"]
        if not task_id:
            raise MeshyApiError(f"POST {path} returned no task id: {str(data)[:200]}")
        _CLAIMED_TASK_IDS.add(task_id)
        created: dict[str, Any] = {"task_id": task_id, "status": status}
        if isinstance(data, dict) and status in TERMINAL_STATUSES:
            created["task"] = data
        return created

    async def _recover_created_task(
        self, path: str, started_ms: int, outcome: str
    ) -> dict[str, Any] | None:
        await self._sleep(self.create_recovery_wait)
        try:
            tasks = await self._list_recent_tasks(path)
        except MeshyApiError as exc:
            raise MeshyCreateUncertainError(
                f"POST {path} had an unknown outcome ({outcome}) and the task list could not "
                f"be checked ({exc}). Check Meshy before re-running."
            ) from exc
        if isinstance(tasks, dict):
            tasks = tasks.get("data") or tasks.get("result") or tasks.get("tasks") or []
        window_start = started_ms - _CREATE_RECOVERY_SKEW_MS
        candidates = [
            task
            for task in tasks or []
            if isinstance(task, dict)
            and task.get("id")
            and str(task["id"]) not in _CLAIMED_TASK_IDS
            and _created_at_ms(task) >= window_start
        ]
        if len(candidates) == 1:
            task = candidates[0]
            _CLAIMED_TASK_IDS.add(str(task["id"]))
            return {
                "task_id": str(task["id"]),
                "status": task.get("status", "PENDING"),
                "recovered": True,
            }
        if len(candidates) > 1:
            ids = ", ".join(str(task["id"]) for task in candidates)
            raise MeshyCreateUncertainError(
                f"POST {path} had an unknown outcome ({outcome}) and {len(candidates)} recent "
                f"tasks could match: {ids}. Pick the right one in Meshy before re-running."
            )
        return None

    def _encode_image(self, path: str) -> str:
        data = Path(path).read_bytes()
        ext = Path(path).suffix.lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "webp": "webp"}.get(ext, "png")
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/{mime};base64,{b64}"

    @staticmethod
    def _i2d_target_formats(cfg: dict[str, Any]) -> list[str]:
        formats = cfg.get("i2d_target_formats") or cfg.get("target_formats") or ["fbx"]
        return list(formats)

    @staticmethod
    def _build_i2d_payload(
        cfg: dict[str, Any],
        *,
        image_url: str | None = None,
        image_urls: list[str] | None = None,
        texture_prompt: str | None = None,
        texture_image_url: str | None = None,
        api_version: str = "v1",
    ) -> dict[str, Any]:
        model_type = cfg.get("model_type", "standard")
        ai_model = cfg.get("ai_model", "meshy-7.1")
        multi_image = image_urls is not None
        payload: dict[str, Any] = {
            "ai_model": ai_model,
            "model_type": model_type,
            "enable_pbr": cfg.get("enable_pbr", True),
            "should_texture": cfg.get("should_texture", True),
            "should_remesh": cfg.get("should_remesh", False),
            "target_formats": MeshyClient._i2d_target_formats(cfg),
            "image_enhancement": cfg.get("image_enhancement", True),
        }

        if model_type == "smart-topology":
            topo_model = cfg.get("smart_topology_model") or "meshy-t2.5"
            if multi_image and topo_model == "meshy-t2.5":
                topo_model = "meshy-t2"
            max_polys = SMART_TOPOLOGY_POLYCOUNT_MAX.get(topo_model, 15000)
            payload["ai_model"] = topo_model
            payload["target_polycount"] = max(
                100, min(int(cfg.get("target_polycount", 4000)), max_polys)
            )
        else:
            payload["topology"] = cfg.get("topology", "quad")
            payload["target_polycount"] = cfg.get("target_polycount", 300000)
            texture_resolution = cfg.get("texture_resolution")
            if texture_resolution:
                payload["texture_resolution"] = texture_resolution
            elif cfg.get("hd_texture"):
                payload["hd_texture"] = True
            geometry = _geometry_resolution(cfg, ai_model, multi_image=multi_image)
            if geometry != "standard":
                payload["geometry_resolution"] = geometry
            if ai_model == "meshy-6" and cfg.get("remove_lighting"):
                payload["remove_lighting"] = True

        if cfg.get("pose_mode"):
            payload["pose_mode"] = cfg["pose_mode"]

        if image_urls is not None:
            payload["image_urls"] = image_urls
        elif image_url is not None:
            payload["image_url"] = image_url
        if texture_image_url:
            payload["texture_image_url"] = texture_image_url
        elif texture_prompt:
            payload["texture_prompt"] = texture_prompt
        if api_version != "v2":
            return payload
        payload.pop("model_type", None)
        payload.pop("remove_lighting", None)
        if payload.pop("hd_texture", None) and "texture_resolution" not in payload:
            payload["texture_resolution"] = "4k"
        if payload.get("should_texture"):
            payload["texture_model"] = cfg.get("texture_model") or "meshy-7"
        return payload

    @staticmethod
    def _build_retexture_payload(
        cfg: dict[str, Any],
        *,
        input_task_id: str,
        text_style_prompt: str | None = None,
        image_style_url: str | None = None,
        api_version: str = "v1",
    ) -> dict[str, Any]:
        prompt = (text_style_prompt or "").strip()
        if not prompt and not image_style_url:
            raise ValueError("Retexture needs a text style prompt or a style image")
        if len(prompt) > RETEXTURE_PROMPT_MAX_CHARS:
            raise ValueError(
                f"Retexture prompt is {len(prompt)} characters; "
                f"Meshy accepts at most {RETEXTURE_PROMPT_MAX_CHARS}"
            )
        payload: dict[str, Any] = {
            "input_task_id": input_task_id,
            "ai_model": cfg.get("retexture_ai_model") or "meshy-7",
            "enable_original_uv": cfg.get("retexture_enable_original_uv", True),
            "enable_pbr": cfg.get("enable_pbr", True),
            "target_formats": MeshyClient._i2d_target_formats(cfg),
        }
        if cfg.get("texture_resolution"):
            payload["texture_resolution"] = cfg["texture_resolution"]
        if api_version == "v2":
            payload = {
                "input_task_id": input_task_id,
                "texture_model": cfg.get("retexture_ai_model") or "meshy-7",
                "uv_mode": "preserve"
                if cfg.get("retexture_enable_original_uv", True)
                else "regenerate",
                "enable_pbr": cfg.get("enable_pbr", True),
                "target_formats": MeshyClient._i2d_target_formats(cfg),
            }
        if cfg.get("texture_resolution"):
            payload["texture_resolution"] = cfg["texture_resolution"]
        if api_version == "v2":
            if image_style_url:
                payload["texture_image_url"] = image_style_url
            else:
                payload["texture_prompt"] = prompt
            return payload
        if image_style_url:
            payload["image_style_url"] = image_style_url
        else:
            payload["text_style_prompt"] = prompt
        return payload

    @staticmethod
    def _rigging_output_path(dest: Path, role: str) -> Path:
        if role == "rig":
            return dest
        if role == "walking":
            return dest.parent / f"{dest.stem}_walking{dest.suffix}"
        if role == "running":
            return dest.parent / f"{dest.stem}_running{dest.suffix}"
        return dest.parent / f"{dest.stem}_{role}{dest.suffix}"

    async def image_to_3d(
        self,
        image_path: str,
        *,
        texture_prompt: str | None = None,
        texture_image_path: str | None = None,
        multi_view_paths: list[str] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cfg = settings or {}
        texture_image_url = self._encode_image(texture_image_path) if texture_image_path else None
        if multi_view_paths and len(multi_view_paths) > 1:
            payload = self._build_i2d_payload(
                cfg,
                image_urls=[self._encode_image(p) for p in multi_view_paths],
                texture_prompt=texture_prompt if not texture_image_url else None,
                texture_image_url=texture_image_url,
                api_version=self.api_version,
            )
            created = await self._create(self._endpoint("multi-image-to-3d"), payload)
            self._task_type_overrides[created["task_id"]] = "multi-image-to-3d"
            return created

        payload = self._build_i2d_payload(
            cfg,
            image_url=self._encode_image(image_path),
            texture_prompt=texture_prompt if not texture_image_url else None,
            texture_image_url=texture_image_url,
            api_version=self.api_version,
        )
        return await self._create(self._endpoint("image-to-3d"), payload)

    async def retexture(
        self,
        input_task_id: str,
        *,
        text_style_prompt: str | None = None,
        image_style_path: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._build_retexture_payload(
            settings or {},
            input_task_id=input_task_id,
            text_style_prompt=text_style_prompt,
            image_style_url=self._encode_image(image_style_path) if image_style_path else None,
            api_version=self.api_version,
        )
        return await self._create(self._endpoint("retexture"), payload)

    async def remesh(
        self,
        input_task_id: str,
        *,
        target_polycount: int,
        topology: str = "quad",
        target_formats: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._create(
            self._endpoint("remesh"),
            {
                "input_task_id": input_task_id,
                "target_polycount": target_polycount,
                "topology": topology,
                "target_formats": target_formats or ["fbx"],
            },
        )

    async def rig(self, input_task_id: str, *, height_meters: float = 1.7) -> dict[str, Any]:
        return await self._create(
            self._endpoint("rigging"),
            {"input_task_id": input_task_id, "height_meters": height_meters},
        )

    async def animate(self, rig_task_id: str, action_id: int, *, fps: int = 30) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rig_task_id": rig_task_id,
            "action_id": action_id,
        }
        if fps:
            payload["post_process"] = {"operation_type": "change_fps", "fps": fps}
        return await self._create(self._endpoint("animation"), payload)

    def _task_path(self, task_id: str, task_type: str) -> str:
        if self.api_version == "v2":
            return f"/openapi/v2/tasks/{task_id}"
        resolved = self._task_type_overrides.get(task_id, task_type)
        return f"{TASK_ENDPOINTS.get(resolved, TASK_ENDPOINTS['image-to-3d'])}/{task_id}"

    async def _get_task_response(self, task_id: str, task_type: str) -> httpx.Response:
        try:
            return await self._get_response(self._task_path(task_id, task_type))
        except MeshyApiError as exc:
            # Multi-image tasks are stored under the "image-to-3d" job type in the DB.
            if self.api_version == "v2" or exc.status_code != 404 or task_type != "image-to-3d":
                raise
            if task_id in self._task_type_overrides:
                raise
            self._task_type_overrides[task_id] = "multi-image-to-3d"
            return await self._get_response(self._task_path(task_id, task_type))

    async def get_task_status(self, task_id: str, task_type: str) -> dict[str, Any]:
        return normalize_task((await self._get_task_response(task_id, task_type)).json())

    async def cancel_task(self, task_id: str) -> bool:
        """DELETE a v2 task. True when Meshy accepted it. 409 means it already started."""
        if self.api_version != "v2":
            return False
        client = await self._get_client()
        try:
            resp = await client.delete(f"/openapi/v2/tasks/{task_id}")
        except httpx.TransportError:
            return False
        if resp.status_code == 409:
            return False
        return resp.status_code < 400

    async def _raise_if_cancelled(
        self, task_id: str, status: str, cancel_event: Any | None
    ) -> None:
        if not cancel_event or not getattr(cancel_event, "is_set", lambda: False)():
            return
        deleted = False
        if self.api_version == "v2" and status == "PENDING":
            deleted = await self.cancel_task(task_id)
        raise MeshyTaskCanceled(task_id, deleted=deleted)

    async def _stream_until_done(
        self,
        task_id: str,
        *,
        cancel_event: Any | None,
        limit: float,
        started: float,
    ) -> dict[str, Any] | None:
        """Follow ``GET /openapi/v2/tasks/{id}/stream``. None means fall back to polling."""
        client = await self._get_client()
        status = "PENDING"
        deadline_ms: float | None = None
        timeout = httpx.Timeout(limit, connect=30.0)
        async with client.stream(
            "GET",
            f"/openapi/v2/tasks/{task_id}/stream",
            headers={"Accept": "text/event-stream"},
            timeout=timeout,
        ) as resp:
            if resp.status_code >= 400:
                raise MeshyApiError(
                    f"task stream failed ({resp.status_code})",
                    status_code=resp.status_code,
                )
            async for line in resp.aiter_lines():
                await self._raise_if_cancelled(task_id, status, cancel_event)
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError("unreadable task event") from exc
                if not isinstance(payload, dict):
                    raise ValueError("unreadable task event")
                status = str(payload.get("status") or status)
                created_at = _created_at_ms(payload)
                if deadline_ms is None and created_at > 0:
                    deadline_ms = created_at + limit * 1000
                if status in TERMINAL_STATUSES:
                    return normalize_task(payload)
                if deadline_ms is not None and time.time() * 1000 >= deadline_ms:
                    raise MeshyPollTimeout(task_id, status, limit)
                if deadline_ms is None and time.monotonic() - started >= limit:
                    raise MeshyPollTimeout(task_id, status, limit)
        return None

    async def poll_until_done(
        self,
        task_id: str,
        task_type: str,
        *,
        timeout: float | None = None,
        cancel_event: Any | None = None,
        initial: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Wait until terminal. v2 follows the task stream, then the Retry-After poll.

        The wait limit counts from the task's ``created_at`` when Meshy reports it, so a
        reattach after a restart does not reset the clock. A create body that is already
        terminal is returned without another status GET.
        """
        if isinstance(initial, dict) and initial.get("status") in TERMINAL_STATUSES:
            return normalize_task(initial)
        limit = self.poll_timeout if timeout is None else float(timeout)
        started = time.monotonic()
        if self.api_version == "v2":
            try:
                streamed = await self._stream_until_done(
                    task_id, cancel_event=cancel_event, limit=limit, started=started
                )
            except (
                MeshyApiError,
                MeshyTransientError,
                httpx.HTTPError,
                ValueError,
                UnicodeError,
            ):
                streamed = None
            else:
                if streamed is not None:
                    return streamed
        return await self._poll_until_done(
            task_id, task_type, limit=limit, started=started, cancel_event=cancel_event
        )

    async def _poll_until_done(
        self,
        task_id: str,
        task_type: str,
        *,
        limit: float,
        started: float,
        cancel_event: Any | None,
    ) -> dict[str, Any]:
        deadline_ms: float | None = None
        status = "PENDING"
        while True:
            await self._raise_if_cancelled(task_id, status, cancel_event)
            delay = self.poll_interval
            try:
                resp = await self._get_task_response(task_id, task_type)
            except MeshyTransientError:
                pass
            else:
                data = normalize_task(resp.json())
                status = data.get("status", "PENDING")
                if status in TERMINAL_STATUSES:
                    return data
                delay = _retry_after_seconds(resp, self.poll_interval)
                created_at = _created_at_ms(data)
                if deadline_ms is None and created_at > 0:
                    deadline_ms = created_at + limit * 1000
            if deadline_ms is not None:
                expired = time.time() * 1000 >= deadline_ms
            else:
                expired = time.monotonic() - started >= limit
            if expired:
                raise MeshyPollTimeout(task_id, status, limit)
            await self._sleep(delay)

    async def _download(self, url: str) -> bytes:
        client = await self._get_download_client()
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.get(url)
            except httpx.TransportError:
                if attempt == attempts:
                    raise
            else:
                if resp.status_code < 500 or attempt == attempts:
                    resp.raise_for_status()
                    return resp.content
            await self._sleep(_backoff_seconds(attempt))
        raise RuntimeError(f"Download failed: {url}")

    async def _write_downloads(self, items: list[tuple[Path, str]]) -> None:
        """Download up to four files at a time. Null and empty URLs are already omitted."""
        if not items:
            return
        sem = asyncio.Semaphore(_DOWNLOAD_CONCURRENCY)

        async def one(path: Path, url: str) -> None:
            async with sem:
                path.write_bytes(await self._download(url))

        await asyncio.gather(*(one(path, url) for path, url in items))

    async def download_model(
        self,
        task_id: str,
        task_type: str,
        *,
        fmt: str = "fbx",
        save_to: str,
        include_textures: bool = True,
    ) -> dict[str, Any]:
        data = await self.get_task_status(task_id, task_type)
        if data.get("status") != "SUCCEEDED":
            raise RuntimeError(f"Task {task_id} not succeeded: {describe_task_failure(data)}")

        result = task_output(data)
        urls: dict[str, str] = {}

        if task_type == "rigging":
            if fmt == "fbx" and result.get("rigged_character_fbx_url"):
                urls["rig"] = result["rigged_character_fbx_url"]
            basic = result.get("basic_animations") or {}
            for key in ("walking_fbx_url", "running_fbx_url"):
                if basic.get(key):
                    urls[key.replace("_fbx_url", "")] = basic[key]
        elif task_type == "animation":
            if result.get("animation_fbx_url"):
                urls["animation"] = result["animation_fbx_url"]
            if result.get("processed_animation_fps_fbx_url"):
                urls["animation_fps"] = result["processed_animation_fps_fbx_url"]
        else:
            model_urls = result.get("model_urls") or {}
            if isinstance(model_urls, dict) and fmt in model_urls:
                urls["model"] = model_urls[fmt]
            elif result.get(f"{fmt}_url"):
                urls["model"] = result[f"{fmt}_url"]

        dest = Path(save_to)
        dest.parent.mkdir(parents=True, exist_ok=True)
        files: list[tuple[Path, str]] = []

        for name, url in urls.items():
            if not url:
                continue
            if task_type == "rigging":
                out = self._rigging_output_path(dest, name)
            elif len(urls) == 1:
                out = dest
            else:
                out = dest.parent / f"{dest.stem}_{name}{dest.suffix}"
            files.append((out, url))

        texture_urls = result.get("texture_urls") or []
        if include_textures and texture_urls:
            tex_dir = dest.parent / "Textures"
            tex_dir.mkdir(parents=True, exist_ok=True)
            for filename, url in _iter_texture_downloads(texture_urls):
                if not url:
                    continue
                files.append((tex_dir / filename, url))

        await self._write_downloads(files)
        return {"local_paths": [str(path) for path, _url in files], "urls": urls}

    async def download_task_thumbnail(
        self, task_id: str, task_type: str, dest: str | Path
    ) -> Path | None:
        data = await self.get_task_status(task_id, task_type)
        if data.get("status") != "SUCCEEDED":
            return None
        url = task_output(data).get("thumbnail_url") or data.get("thumbnail_url")
        if not url:
            return None
        out = Path(dest)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(await self._download(url))
        return out

    async def _texture_urls_from_task(self, task_id: str, task_type: str) -> Any:
        data = await self.get_task_status(task_id, task_type)
        if data.get("status") != "SUCCEEDED":
            return []
        return task_output(data).get("texture_urls") or []

    async def _chosen_texture_urls(
        self, sources: list[tuple[str, str | None, str]]
    ) -> tuple[Any, str]:
        for source_label, task_id, task_type in sources:
            if not task_id:
                continue
            urls = await self._texture_urls_from_task(task_id, task_type)
            if urls:
                return urls, source_label
        return [], "none"

    @staticmethod
    def _texture_sources(
        i2d_task_id: str | None,
        remesh_task_id: str | None,
        retexture_task_id: str | None,
    ) -> list[tuple[str, str | None, str]]:
        first = (
            ("retexture", retexture_task_id, "retexture")
            if retexture_task_id
            else ("i2d", i2d_task_id, "image-to-3d")
        )
        return [first, ("remesh", remesh_task_id, "remesh")]

    async def download_meshy_package(
        self,
        rig_task_id: str,
        *,
        i2d_task_id: str | None = None,
        remesh_task_id: str | None = None,
        retexture_task_id: str | None = None,
        source_dir: str | Path,
        textures_dir: str | Path,
        zip_path: str | Path,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Download Meshy rig export: rig FBX, walk/run animations, and PBR PNGs."""

        def _progress(message: str) -> None:
            if progress:
                progress(message)

        rig_data = await self.get_task_status(rig_task_id, "rigging")
        if rig_data.get("status") != "SUCCEEDED":
            raise RuntimeError(
                f"Rig task {rig_task_id} not succeeded: {describe_task_failure(rig_data)}"
            )

        rig_result = task_output(rig_data)
        source = Path(source_dir)
        textures = Path(textures_dir)
        source.mkdir(parents=True, exist_ok=True)
        textures.mkdir(parents=True, exist_ok=True)
        zip_file = Path(zip_path)
        zip_file.parent.mkdir(parents=True, exist_ok=True)

        entries: list[tuple[str, Path]] = []
        files: list[tuple[Path, str]] = []

        rig_url = rig_result.get("rigged_character_fbx_url")
        rig_path: Path | None = None
        if rig_url:
            rig_name = _basename_from_url(rig_url, "Character_output.fbx")
            rig_path = source / rig_name
            _progress(f"Downloading rig FBX ({rig_name}) — large file, may take 1–2 minutes")
            files.append((rig_path, rig_url))
            entries.append((f"Source/{rig_name}", rig_path))

        basic = rig_result.get("basic_animations") or {}
        for key in ("walking_fbx_url", "running_fbx_url"):
            url = basic.get(key)
            if not url:
                continue
            anim_name = _basename_from_url(url, f"{key}.fbx")
            anim_path = source / anim_name
            _progress(f"Downloading locomotion FBX ({anim_name})")
            files.append((anim_path, url))
            entries.append((f"Source/{anim_name}", anim_path))

        texture_urls, texture_source = await self._chosen_texture_urls(
            self._texture_sources(i2d_task_id, remesh_task_id, retexture_task_id)
        )
        if texture_urls:
            _progress(f"Downloading PBR textures from Meshy ({texture_source})")
            for filename, url in _iter_texture_downloads(texture_urls):
                if not url:
                    continue
                tex_path = textures / filename
                files.append((tex_path, url))
                entries.append((f"Textures/{filename}", tex_path))
        await self._write_downloads(files)
        if texture_source == "none" and rig_path and rig_path.is_file():
            _progress("Extracting textures from rig FBX (API texture URLs unavailable)")
            extracted = _extract_textures_from_fbx(rig_path.read_bytes(), textures)
            for path in extracted:
                entries.append((f"Textures/{path.name}", path))
            if extracted:
                texture_source = "rig_fbx"

        downloaded = [str(path) for _, path in entries]
        _progress("Writing Meshy export zip")
        with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, path in entries:
                zf.write(path, arcname=arcname)

        return {
            "local_paths": downloaded + [str(zip_file)],
            "zip_path": str(zip_file),
            "primary_fbx": str(source / _basename_from_url(rig_url, "Character_output.fbx"))
            if rig_url
            else None,
            "texture_source": texture_source,
        }

    async def download_i2d_preview_assets(
        self,
        task_id: str,
        *,
        previews_dir: str | Path,
        source_dir: str | Path,
        textures_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        """Fetch thumbnail, GLB, and optional PBR maps from a completed i2d task."""
        data = await self.get_task_status(task_id, "image-to-3d")
        if data.get("status") != "SUCCEEDED":
            raise RuntimeError(f"i2d task {task_id} not succeeded: {describe_task_failure(data)}")

        result = task_output(data)
        previews = Path(previews_dir)
        source = Path(source_dir)
        previews.mkdir(parents=True, exist_ok=True)
        source.mkdir(parents=True, exist_ok=True)

        out: dict[str, Any] = {
            "thumbnail_path": None,
            "glb_path": None,
            "texture_paths": [],
            "thumbnail_url": data.get("thumbnail_url") or result.get("thumbnail_url"),
        }

        files: list[tuple[Path, str]] = []
        thumb_url = out["thumbnail_url"]
        if thumb_url:
            thumb_path = previews / "meshy_thumbnail.png"
            files.append((thumb_path, thumb_url))
            out["thumbnail_path"] = str(thumb_path)

        model_urls = result.get("model_urls") or {}
        glb_url = model_urls.get("glb") if isinstance(model_urls, dict) else None
        if glb_url:
            glb_path = source / "Character_preview.glb"
            files.append((glb_path, glb_url))
            out["glb_path"] = str(glb_path)

        texture_urls = result.get("texture_urls") or []
        if textures_dir and texture_urls:
            tex_root = Path(textures_dir)
            tex_root.mkdir(parents=True, exist_ok=True)
            for filename, url in _iter_texture_downloads(texture_urls):
                if not url:
                    continue
                tex_path = tex_root / filename
                files.append((tex_path, url))
                out["texture_paths"].append(str(tex_path))

        await self._write_downloads(files)
        return out


class FakeMeshyClient(MeshyClient):
    """Offline fake for tests and --dry-run."""

    # Shared like a server: each stage builds its own client but must see earlier tasks.
    _server_tasks: dict[str, dict[str, Any]] = {}

    def __init__(self) -> None:
        super().__init__(api_key="fake")
        self._tasks = FakeMeshyClient._server_tasks

    async def close(self) -> None:
        pass

    async def health_check(self) -> dict[str, Any]:
        return {"available": True, "reason": "dry-run"}

    def _make_task(
        self,
        task_type: str,
        extra: dict[str, Any] | None = None,
        *,
        credits: int = 0,
    ) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        data = {
            "task_id": task_id,
            "status": "PENDING",
            "task_type": task_type,
        }
        self._tasks[task_id] = {
            "status": "SUCCEEDED",
            "progress": 100,
            "task_type": task_type,
            "consumed_credits": credits,
            "face_count": extra.get("face_count", 45000) if extra else 45000,
            "thumbnail_url": "https://example.com/thumbnail.png",
            "result": {
                "model_urls": {
                    "fbx": "https://example.com/fake.fbx",
                    "glb": "https://example.com/fake.glb",
                },
                "texture_urls": [
                    {
                        "base_color": "https://example.com/base_color.png",
                        "normal": "https://example.com/normal.png",
                        "metallic": "https://example.com/metallic.png",
                        "roughness": "https://example.com/roughness.png",
                    }
                ],
                "rigged_character_fbx_url": "https://example.com/Character_output.fbx",
                "basic_animations": {
                    "walking_fbx_url": "https://example.com/Animation_Walking_withSkin.fbx",
                    "running_fbx_url": "https://example.com/Animation_Running_withSkin.fbx",
                },
                "animation_fbx_url": "https://example.com/anim.fbx",
            },
            **(extra or {}),
        }
        return data

    async def image_to_3d(self, image_path: str, **kwargs: Any) -> dict[str, Any]:
        return self._make_task("image-to-3d", {"face_count": 320000}, credits=30)

    async def retexture(self, input_task_id: str, **kwargs: Any) -> dict[str, Any]:
        self._build_retexture_payload(
            kwargs.get("settings") or {},
            input_task_id=input_task_id,
            text_style_prompt=kwargs.get("text_style_prompt"),
            image_style_url="data:image/png;base64," if kwargs.get("image_style_path") else None,
            api_version=self.api_version,
        )
        return self._make_task(
            "retexture", {"face_count": 320000, "input_task_id": input_task_id}, credits=10
        )

    async def remesh(self, input_task_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._make_task(
            "remesh", {"face_count": kwargs.get("target_polycount", 25000)}, credits=5
        )

    async def rig(self, input_task_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._make_task("rigging", credits=5)

    async def animate(self, rig_task_id: str, action_id: int, **kwargs: Any) -> dict[str, Any]:
        return self._make_task("animation", {"action_id": action_id}, credits=3)

    async def get_task_status(self, task_id: str, task_type: str) -> dict[str, Any]:
        if task_id not in self._tasks:
            self._tasks[task_id] = {
                "status": "SUCCEEDED",
                "progress": 100,
                "task_type": task_type,
                "face_count": 45000,
                "result": {},
            }
        return {"id": task_id, **self._tasks[task_id]}

    async def poll_until_done(self, task_id: str, task_type: str, **kwargs: Any) -> dict[str, Any]:
        return await self.get_task_status(task_id, task_type)

    async def download_task_thumbnail(
        self, task_id: str, task_type: str, dest: str | Path
    ) -> Path | None:
        out = Path(dest)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_PNG_SIGNATURE + b"\x00" * 32 + _PNG_IEND)
        return out

    async def download_meshy_package(
        self,
        rig_task_id: str,
        *,
        i2d_task_id: str | None = None,
        remesh_task_id: str | None = None,
        retexture_task_id: str | None = None,
        source_dir: str | Path,
        textures_dir: str | Path,
        zip_path: str | Path,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        source = Path(source_dir)
        textures = Path(textures_dir)
        source.mkdir(parents=True, exist_ok=True)
        textures.mkdir(parents=True, exist_ok=True)
        zip_file = Path(zip_path)
        zip_file.parent.mkdir(parents=True, exist_ok=True)

        rig_name = "Character_output.fbx"
        rig_path = source / rig_name
        rig_path.write_bytes(b"FAKE_RIG_FBX")
        entries = [(f"Source/{rig_name}", rig_path)]

        for anim_name in (
            "Animation_Walking_withSkin.fbx",
            "Animation_Running_withSkin.fbx",
        ):
            anim_path = source / anim_name
            anim_path.write_bytes(b"FAKE_ANIM_FBX")
            entries.append((f"Source/{anim_name}", anim_path))

        for tex_name in ("base_color.png", "normal.png", "metallic.png", "roughness.png"):
            tex_path = textures / tex_name
            tex_path.write_bytes(b"FAKE_PNG")
            entries.append((f"Textures/{tex_name}", tex_path))

        with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, path in entries:
                zf.write(path, arcname=arcname)

        downloaded = [str(path) for _, path in entries]
        return {
            "local_paths": downloaded + [str(zip_file)],
            "zip_path": str(zip_file),
            "primary_fbx": str(rig_path),
            "texture_source": "retexture" if retexture_task_id else "i2d",
        }

    async def download_i2d_preview_assets(
        self,
        task_id: str,
        *,
        previews_dir: str | Path,
        source_dir: str | Path,
        textures_dir: str | Path | None = None,
    ) -> dict[str, Any]:
        previews = Path(previews_dir)
        source = Path(source_dir)
        previews.mkdir(parents=True, exist_ok=True)
        source.mkdir(parents=True, exist_ok=True)

        thumb_path = previews / "meshy_thumbnail.png"
        thumb_path.write_bytes(_PNG_SIGNATURE + b"\x00" * 32 + _PNG_IEND)

        glb_path = source / "Character_preview.glb"
        glb_path.write_bytes(b"FAKE_GLB")

        texture_paths: list[str] = []
        if textures_dir:
            tex_root = Path(textures_dir)
            tex_root.mkdir(parents=True, exist_ok=True)
            for name in ("base_color.png", "normal.png", "metallic.png", "roughness.png"):
                tex_path = tex_root / name
                tex_path.write_bytes(_PNG_SIGNATURE + b"\x00" * 32 + _PNG_IEND)
                texture_paths.append(str(tex_path))

        return {
            "thumbnail_path": str(thumb_path),
            "glb_path": str(glb_path),
            "texture_paths": texture_paths,
            "thumbnail_url": "https://example.com/thumbnail.png",
        }

    async def download_model(
        self,
        task_id: str,
        task_type: str,
        *,
        fmt: str = "fbx",
        save_to: str,
        include_textures: bool = True,
    ) -> dict[str, Any]:
        dest = Path(save_to)
        dest.parent.mkdir(parents=True, exist_ok=True)
        downloaded: list[str] = []

        if task_type == "rigging":
            roles = ("rig", "walking", "running")
            for role in roles:
                out = self._rigging_output_path(dest, role)
                out.write_bytes(b"FAKE_FBX")
                downloaded.append(str(out))
        else:
            dest.write_bytes(b"FAKE_FBX")
            downloaded.append(str(dest))

        if include_textures:
            tex_dir = dest.parent / "Textures"
            tex_dir.mkdir(exist_ok=True)
            tex_path = tex_dir / "base.png"
            tex_path.write_bytes(b"FAKE_PNG")
            downloaded.append(str(tex_path))
        return {"local_paths": downloaded, "urls": {}}
