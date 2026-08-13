"""Poll Unity Editor import result JSON written by com.assetassembly.import."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


async def poll_import_result(
    result_path: Path,
    *,
    timeout_seconds: float = 300.0,
    interval_seconds: float = 2.0,
    cancel_event: Any | None = None,
) -> dict[str, Any]:
    """Wait for unity_import_result.json to appear and return parsed payload."""
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while asyncio.get_event_loop().time() < deadline:
        if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
            raise asyncio.CancelledError("Import poll cancelled")
        if result_path.is_file():
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        await asyncio.sleep(interval_seconds)
    return {"ok": False, "errors": [f"Timed out waiting for {result_path.name}"]}


def import_request_path(asset_root: Path) -> Path:
    return asset_root / ".aaa" / "import_request.json"


def import_result_path(asset_root: Path) -> Path:
    return asset_root / ".aaa" / "unity_import_result.json"


def write_import_request(
    asset_root: Path,
    *,
    slug: str,
    asset_kind: str,
    texture_resolution: str = "8k",
) -> Path:
    aaa_dir = asset_root / ".aaa"
    aaa_dir.mkdir(parents=True, exist_ok=True)
    result_path = import_result_path(asset_root)
    if result_path.exists():
        result_path.unlink()
    request = {
        "slug": slug,
        "asset_kind": asset_kind,
        "texture_resolution": texture_resolution,
    }
    path = import_request_path(asset_root)
    path.write_text(json.dumps(request, indent=2), encoding="utf-8")
    return path
