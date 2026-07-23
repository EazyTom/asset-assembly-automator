from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

from asset_assembly_automator.clients.concept_images import (
    persist_concept_item,
    write_placeholder_png,
)
from asset_assembly_automator.clients.higgsfield_mcp import HiggsfieldMcpClient
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.secrets import higgsfield_credentials


@runtime_checkable
class ConceptProvider(Protocol):
    async def generate_image(
        self, prompt: str, *, model: str | None = None, count: int = 1
    ) -> dict[str, Any]: ...

    async def remove_background(self, media_id: str) -> dict[str, Any]: ...

    async def get_cost(self, prompt: str, *, model: str | None = None) -> dict[str, Any]: ...


class FakeHiggsfieldClient:
    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir

    async def generate_image(
        self, prompt: str, *, model: str | None = None, count: int = 1
    ) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        out_dir = self.output_dir or Path(".")
        out_dir.mkdir(parents=True, exist_ok=True)
        local = write_placeholder_png(
            out_dir / f"concept_hf_{job_id[:8]}.png",
            title="Dry-run concept",
            subtitle=(prompt or "")[:80],
        )
        return {
            "results": [
                {
                    "id": job_id,
                    "status": "completed",
                    "model": model or "soul_2",
                    "params": {"prompt": prompt},
                    "local_path": str(local),
                }
            ]
        }

    async def remove_background(self, media_id: str) -> dict[str, Any]:
        return {"results": [{"id": media_id, "status": "completed"}]}

    async def get_cost(self, prompt: str, *, model: str | None = None) -> dict[str, Any]:
        return {"cost": {"credits": 1, "credits_exact": 1.0}}


class RestHiggsfieldClient:
    """Higgsfield platform REST client (platform.higgsfield.ai)."""

    def __init__(self, output_dir: Path, credentials: str | None = None) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.credentials = credentials or higgsfield_credentials()
        settings = get_settings()
        self.base_url = settings.higgsfield.api_base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._jobs: dict[str, dict[str, Any]] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if not self.credentials:
            raise RuntimeError(
                "Higgsfield REST credentials not configured. Set HF_CREDENTIALS or "
                "HIGGSFIELD_API_KEY + HIGGSFIELD_SECRET, or switch higgsfield.provider to mcp."
            )
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Key {self.credentials}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _payload_for_model(self, prompt: str, model: str) -> tuple[str, dict[str, Any]]:
        settings = get_settings()
        aspect = settings.higgsfield.aspect_ratio
        if model in {"soul", "soul_2"}:
            return "/v1/text2image/soul", {
                "prompt": prompt,
                "width_and_height": "1024x1536",
                "quality": "hd",
                "batch_size": 1,
            }
        return "flux-pro/kontext/max/text-to-image", {
            "prompt": prompt,
            "aspect_ratio": aspect,
            "safety_tolerance": 2,
        }

    async def _poll_request(self, request_id: str) -> dict[str, Any]:
        client = await self._get_client()
        for _ in range(120):
            resp = await client.get(f"/requests/{request_id}/status")
            resp.raise_for_status()
            data = resp.json()
            status = str(data.get("status", "")).lower()
            if status in {"completed", "failed", "canceled", "nsfw", "ip_detected"}:
                if status != "completed":
                    raise RuntimeError(f"Higgsfield generation {request_id} failed: {status}")
                return data
            await asyncio.sleep(2)
        raise TimeoutError(f"Higgsfield request {request_id} timed out")

    def _urls_from_status(self, data: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for img in data.get("images") or []:
            if isinstance(img, dict) and img.get("url"):
                urls.append(str(img["url"]))
        video = data.get("video")
        if isinstance(video, dict) and video.get("url"):
            urls.append(str(video["url"]))
        for job in data.get("jobs") or []:
            results = job.get("results") or {}
            raw = results.get("raw")
            if isinstance(raw, dict) and raw.get("url"):
                urls.append(str(raw["url"]))
            if isinstance(results.get("rawUrl"), str):
                urls.append(str(results["rawUrl"]))
        return urls

    async def generate_image(
        self, prompt: str, *, model: str | None = None, count: int = 1
    ) -> dict[str, Any]:
        settings = get_settings()
        model_name = model or settings.higgsfield.default_image_model
        endpoint, payload = self._payload_for_model(prompt, model_name)
        client = await self._get_client()
        resp = await client.post(endpoint, json=payload)
        resp.raise_for_status()
        data = resp.json()

        request_id = data.get("request_id") or data.get("id")
        if request_id:
            data = await self._poll_request(str(request_id))

        urls = self._urls_from_status(data)
        if not urls:
            raise RuntimeError(
                "Higgsfield completed but returned no image URLs. "
                f"Response keys: {list(data.keys())}"
            )

        results: list[dict[str, Any]] = []
        for i, url in enumerate(urls[: max(1, count)]):
            job_id = str(data.get("request_id") or uuid.uuid4())
            item = {
                "id": f"{job_id}-{i}",
                "status": "completed",
                "model": model_name,
                "params": {"prompt": prompt},
                "results": {"rawUrl": url},
            }
            local_path, meta = await persist_concept_item(
                item, self.output_dir, provider="higgsfield", http=client
            )
            item["local_path"] = str(local_path)
            item["download_meta"] = meta
            self._jobs[item["id"]] = item
            results.append(item)

        return {"results": results}

    async def remove_background(self, media_id: str) -> dict[str, Any]:
        return {"results": [{"id": media_id, "status": "completed"}]}

    async def get_cost(self, prompt: str, *, model: str | None = None) -> dict[str, Any]:
        return {"cost": {"credits": 1, "credits_exact": 1.0}}

    def save_job_manifest(self, pipeline_id: int) -> Path:
        path = self.output_dir / f"pipeline_{pipeline_id}_higgs_jobs.json"
        path.write_text(json.dumps(self._jobs, indent=2), encoding="utf-8")
        return path


class McpHiggsfieldAdapter:
    """Higgsfield via hosted MCP (same server as the Cursor plugin)."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._mcp = HiggsfieldMcpClient()
        self._http = httpx.AsyncClient(timeout=120.0, follow_redirects=True)
        self._jobs: dict[str, dict[str, Any]] = {}

    async def close(self) -> None:
        await self._http.aclose()

    async def generate_image(
        self, prompt: str, *, model: str | None = None, count: int = 1
    ) -> dict[str, Any]:
        settings = get_settings()
        model_name = model or settings.higgsfield.default_image_model
        payload = await self._mcp.generate_image(
            prompt,
            model=model_name,
            count=count,
            aspect_ratio=settings.higgsfield.aspect_ratio,
        )
        items = payload.get("results") or []
        saved: list[dict[str, Any]] = []
        for item in items:
            local_path, meta = await persist_concept_item(
                item, self.output_dir, provider="higgsfield", http=self._http
            )
            item = dict(item)
            item["local_path"] = str(local_path)
            item["download_meta"] = meta
            self._jobs[str(item.get("id"))] = item
            saved.append(item)
        return {"results": saved}

    async def remove_background(self, media_id: str) -> dict[str, Any]:
        payload = await self._mcp.call_tool(
            "remove_background",
            {"params": {"media_id": media_id}},
        )
        return payload

    async def get_cost(self, prompt: str, *, model: str | None = None) -> dict[str, Any]:
        return await self._mcp.get_cost(prompt, model=model)

    def save_job_manifest(self, pipeline_id: int) -> Path:
        path = self.output_dir / f"pipeline_{pipeline_id}_higgs_jobs.json"
        path.write_text(json.dumps(self._jobs, indent=2), encoding="utf-8")
        return path


def create_higgsfield_client(dry_run: bool, output_dir: Path) -> ConceptProvider:
    if dry_run:
        return FakeHiggsfieldClient(output_dir)
    settings = get_settings()
    if settings.higgsfield.provider == "rest":
        return RestHiggsfieldClient(output_dir)
    return McpHiggsfieldAdapter(output_dir)
