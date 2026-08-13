from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx

from asset_assembly_automator.clients.concept_images import (
    download_image_url,
    write_placeholder_png,
)
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.secrets import magnific_api_key

logger = logging.getLogger(__name__)

MagnificUpscaleMode = Literal["precision_v2", "creative"]
TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED"})
POLL_STATUSES = frozenset({"CREATED", "IN_PROGRESS"})


def _parse_scale_factor(scale: str | int) -> int:
    if isinstance(scale, int):
        return max(2, min(16, scale))
    raw = str(scale).strip().lower().rstrip("x")
    try:
        return max(2, min(16, int(raw)))
    except ValueError as exc:
        raise ValueError(f"Invalid scale factor: {scale}") from exc


def _encode_image_file(path: str | Path) -> str:
    data = Path(path).read_bytes()
    ext = Path(path).suffix.lower()
    mime = "jpeg" if ext in {".jpg", ".jpeg"} else "png"
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


class FakeMagnificClient:
    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        count: int = 1,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        out_dir = self.output_dir or Path(".")
        out_dir.mkdir(parents=True, exist_ok=True)
        local = write_placeholder_png(
            out_dir / f"concept_magnific_{job_id[:8]}.png",
            title="Dry-run Magnific concept",
            subtitle=(prompt or "")[:80],
        )
        return {
            "results": [
                {
                    "id": job_id,
                    "status": "completed",
                    "model": model or "super_real",
                    "resolution": resolution or "2k",
                    "params": {"prompt": prompt},
                    "local_path": str(local),
                }
            ]
        }

    async def upscale_image(
        self,
        image_path: str,
        *,
        scale_factor: str | int = "2x",
        mode: MagnificUpscaleMode = "precision_v2",
        flavor: str | None = "sublime",
        prompt: str | None = None,
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        out_dir = self.output_dir or Path(".")
        out_dir.mkdir(parents=True, exist_ok=True)
        scale = _parse_scale_factor(scale_factor)
        local = write_placeholder_png(
            out_dir / f"concept_magnific_up_{job_id[:8]}.png",
            title=f"Dry-run Uprez {scale}x",
            subtitle=f"{mode} · {(prompt or '')[:60]}",
        )
        return {
            "id": job_id,
            "status": "completed",
            "local_path": str(local),
            "scale_factor": scale,
            "mode": mode,
        }

    async def get_cost(self, action: str, **kwargs: Any) -> dict[str, Any]:
        return {"cost": {"credits": 1, "credits_exact": 1.0, "action": action}}

    async def health_check(self) -> dict[str, Any]:
        return {"available": True, "reason": "dry-run"}


class MagnificClient:
    """Magnific REST client for Mystic text-to-image and upscaler APIs."""

    def __init__(self, output_dir: Path, api_key: str | None = None) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        settings = get_settings()
        self.base_url = settings.magnific.base_url.rstrip("/")
        self.api_key = api_key or magnific_api_key() or ""
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if not self.api_key:
            raise RuntimeError(
                "Magnific API key not configured. Set MAGNIFIC_API_KEY in secrets.env "
                "or add magnific-api.key at repo root."
            )
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-magnific-api-key": self.api_key,
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=180.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> dict[str, Any]:
        if not self.api_key:
            return {"available": False, "reason": "MAGNIFIC_API_KEY not configured"}
        try:
            client = await self._get_client()
            resp = await client.get("/v1/user/profile")
            if resp.status_code == 401:
                return {"available": False, "reason": "Magnific API key rejected (401)"}
            resp.raise_for_status()
            return {"available": True}
        except Exception as exc:
            return {"available": False, "reason": str(exc)}

    @staticmethod
    def _task_payload(data: dict[str, Any]) -> dict[str, Any]:
        inner = data.get("data")
        if isinstance(inner, dict):
            return inner
        return data

    async def _poll_task(
        self,
        task_id: str,
        status_path: str,
        *,
        label: str,
        max_attempts: int = 120,
    ) -> dict[str, Any]:
        client = await self._get_client()
        delay = 2.0
        for attempt in range(max_attempts):
            resp = await client.get(status_path.format(task_id=task_id))
            resp.raise_for_status()
            payload = self._task_payload(resp.json())
            status = str(payload.get("status", "")).upper()
            logger.info(
                "Magnific poll",
                extra={"task_id": task_id, "status": status, "label": label, "attempt": attempt},
            )
            if status == "COMPLETED":
                return payload
            if status == "FAILED":
                raise RuntimeError(f"Magnific {label} task {task_id} failed")
            if status not in POLL_STATUSES and status not in TERMINAL_STATUSES:
                logger.warning("Magnific unknown status %s for %s", status, task_id)
            await asyncio.sleep(delay)
            delay = min(delay * 1.1, 10.0)
        raise TimeoutError(f"Magnific {label} task {task_id} timed out")

    async def _download_generated(
        self,
        payload: dict[str, Any],
        *,
        stem: str,
    ) -> Path:
        urls = payload.get("generated") or []
        if not urls:
            raise RuntimeError("Magnific task completed but returned no image URLs")
        dest = self.output_dir / f"{stem}.png"
        client = await self._get_client()
        await download_image_url(str(urls[0]), dest, client=client)
        return dest

    async def generate_image(
        self,
        prompt: str,
        *,
        model: str | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        count: int = 1,
    ) -> dict[str, Any]:
        settings = get_settings()
        body: dict[str, Any] = {
            "prompt": prompt,
            "model": model or settings.magnific.mystic_model,
            "resolution": resolution or settings.magnific.resolution,
            "aspect_ratio": aspect_ratio or settings.magnific.aspect_ratio,
        }
        client = await self._get_client()
        resp = await client.post("/v1/ai/mystic", json=body)
        resp.raise_for_status()
        created = self._task_payload(resp.json())
        task_id = str(created.get("task_id") or "")
        if not task_id:
            raise RuntimeError(f"Magnific Mystic returned no task_id: {created}")
        logger.info("Magnific Mystic task created", extra={"task_id": task_id})

        if str(created.get("status", "")).upper() != "COMPLETED":
            created = await self._poll_task(
                task_id,
                "/v1/ai/mystic/{task_id}",
                label="mystic",
            )

        job_id = task_id
        local_path = await self._download_generated(created, stem=f"concept_magnific_{job_id[:8]}")
        return {
            "results": [
                {
                    "id": job_id,
                    "status": "completed",
                    "model": body["model"],
                    "resolution": body["resolution"],
                    "params": {"prompt": prompt},
                    "local_path": str(local_path),
                }
            ]
        }

    async def upscale_image(
        self,
        image_path: str,
        *,
        scale_factor: str | int = "2x",
        mode: MagnificUpscaleMode = "precision_v2",
        flavor: str | None = "sublime",
        prompt: str | None = None,
    ) -> dict[str, Any]:
        scale = _parse_scale_factor(scale_factor)
        image_data = _encode_image_file(image_path)
        settings = get_settings()

        if mode == "creative":
            body: dict[str, Any] = {
                "image": image_data,
                "scale_factor": f"{scale}x",
            }
            if prompt:
                body["prompt"] = prompt
            post_path = "/v1/ai/image-upscaler"
            poll_path = "/v1/ai/image-upscaler/{task_id}"
            label = "upscaler-creative"
        else:
            body = {
                "image": image_data,
                "scale_factor": scale,
                "sharpen": settings.magnific.precision_sharpen,
                "smart_grain": settings.magnific.precision_smart_grain,
                "ultra_detail": settings.magnific.precision_ultra_detail,
                "flavor": flavor or settings.magnific.upscale_flavor,
            }
            post_path = "/v1/ai/image-upscaler-precision-v2"
            poll_path = "/v1/ai/image-upscaler-precision-v2/{task_id}"
            label = "upscaler-precision-v2"

        client = await self._get_client()
        resp = await client.post(post_path, json=body)
        resp.raise_for_status()
        created = self._task_payload(resp.json())
        task_id = str(created.get("task_id") or "")
        if not task_id:
            raise RuntimeError(f"Magnific {label} returned no task_id: {created}")
        logger.info("Magnific upscale task created", extra={"task_id": task_id, "mode": mode})

        if str(created.get("status", "")).upper() != "COMPLETED":
            created = await self._poll_task(task_id, poll_path, label=label)

        local_path = await self._download_generated(
            created,
            stem=f"concept_magnific_up_{task_id[:8]}",
        )
        return {
            "id": task_id,
            "status": "completed",
            "local_path": str(local_path),
            "scale_factor": scale,
            "mode": mode,
        }

    async def get_cost(self, action: str, **kwargs: Any) -> dict[str, Any]:
        if action == "upscale":
            scale = _parse_scale_factor(kwargs.get("scale_factor", "2x"))
            # Rough informational estimate from Magnific docs (output-area pricing).
            base = 0.10
            multiplier = {2: 1.0, 4: 2.0, 8: 5.0, 16: 10.0}.get(scale, float(scale) / 2.0)
            euros = round(base * multiplier, 2)
            return {"cost": {"credits": None, "euros_estimate": euros, "action": action}}
        return {"cost": {"credits": None, "euros_estimate": 0.20, "action": action}}


def create_magnific_client(dry_run: bool, output_dir: Path) -> MagnificClient | FakeMagnificClient:
    if dry_run:
        return FakeMagnificClient(output_dir)
    return MagnificClient(output_dir)
