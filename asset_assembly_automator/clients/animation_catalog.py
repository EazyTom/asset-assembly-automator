from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from asset_assembly_automator.core.config import get_settings

LIBRARY_PATH = "/openapi/v1/animations/library"
LIBRARY_PATH_V2 = "/openapi/v2/animations/library"
PUBLIC_CATALOG_URL = "https://api.meshy.ai/web/public/animations/resources"
# Walk/run are free with rig download; these idles are requested in meshy_animate (3 credits each).
STANDARD_IDLE_ANIMATIONS = ["idle3", "idle4", "idle12"]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def normalize_catalog_response(data: Any) -> list[dict[str, Any]]:
    """Flatten either the official library array or the public ``{result: {list}}`` shape."""
    if isinstance(data, dict):
        inner = data.get("result", data)
        if isinstance(inner, dict):
            inner = inner.get("list") or inner.get("items") or inner.get("animations") or []
        data = inner
    if not isinstance(data, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in data:
        if not isinstance(raw, dict):
            continue
        action_id = raw.get("action_id", raw.get("id"))
        try:
            action_id = int(action_id)
        except (TypeError, ValueError):
            continue
        items.append(
            {
                "action_id": action_id,
                "action_name": raw.get("name") or raw.get("action_name") or "",
                "key": raw.get("key") or "",
                "category": raw.get("category") or "",
                "sub_category": raw.get("sub_category") or raw.get("subCategory") or "",
                "preview_url": raw.get("preview_url") or raw.get("previewUrl") or "",
            }
        )
    return items


class AnimationCatalog:
    def __init__(self, cache_path: Path | None = None, *, api_key: str | None = None) -> None:
        settings = get_settings()
        self.cache_path = cache_path or (settings.paths.app_data / "animation_catalog.json")
        self.base_url = settings.meshy.base_url.rstrip("/")
        self._api_key = api_key
        self._items: list[dict[str, Any]] = []

    def _load_cache(self) -> list[dict[str, Any]]:
        try:
            cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        # Caches written before the official endpoint lack "key"; refetch those.
        if isinstance(cached, list) and cached and "key" in cached[0]:
            return cached
        return []

    async def _fetch(self) -> list[dict[str, Any]]:
        api_key = self._api_key
        if api_key is None:
            from asset_assembly_automator.core.secrets import meshy_api_key

            api_key = meshy_api_key()
        paths = [LIBRARY_PATH]
        if get_settings().meshy.api_version == "v2":
            paths.insert(0, LIBRARY_PATH_V2)
        async with httpx.AsyncClient(timeout=60) as client:
            if api_key:
                for path in paths:
                    try:
                        resp = await client.get(
                            f"{self.base_url}{path}",
                            headers={"Authorization": f"Bearer {api_key}"},
                        )
                        if resp.status_code == 404 and path != paths[-1]:
                            continue
                        resp.raise_for_status()
                        items = normalize_catalog_response(resp.json())
                        if items:
                            return items
                    except (httpx.HTTPError, ValueError):
                        if path != paths[-1]:
                            continue
                        break
            resp = await client.get(PUBLIC_CATALOG_URL)
            resp.raise_for_status()
            return normalize_catalog_response(resp.json())

    async def sync(self, *, force: bool = False) -> list[dict[str, Any]]:
        if not force and self.cache_path.exists():
            mtime = datetime.fromtimestamp(self.cache_path.stat().st_mtime, tz=UTC)
            if datetime.now(UTC) - mtime < timedelta(days=1):
                cached = self._load_cache()
                if cached:
                    self._items = cached
                    return self._items
        items = await self._fetch()
        if items:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(items, indent=2), encoding="utf-8")
        self._items = items
        return items

    def _ensure_loaded(self) -> None:
        if not self._items and self.cache_path.exists():
            self._items = self._load_cache()

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        self._ensure_loaded()
        q = query.lower()
        results = [
            i
            for i in self._items
            if q in (i.get("action_name") or "").lower()
            or q in (i.get("key") or "").lower()
            or q in (i.get("category") or "").lower()
        ]
        return results[:limit]

    def find(self, query: str) -> dict[str, Any] | None:
        """Exact match on key or name ignoring case/punctuation ("idle3" == "Idle_3")."""
        self._ensure_loaded()
        target = _slug(query)
        if not target:
            return None
        for item in self._items:
            if target in (_slug(item.get("key") or ""), _slug(item.get("action_name") or "")):
                return item
        return None

    def resolve(self, queries: list[str]) -> list[dict[str, Any]]:
        selections: list[dict[str, Any]] = []
        for query in queries:
            picked = self.find(query)
            if picked and picked.get("action_id", -1) >= 0:
                selections.append(
                    {
                        "action_id": picked["action_id"],
                        "action_name": picked["action_name"],
                        "is_default_included": True,
                    }
                )
        return selections

    def resolve_standard_idles(self) -> list[dict[str, Any]]:
        """Resolve idle3, idle4, idle12 from the Meshy animation catalog."""
        return self.resolve(STANDARD_IDLE_ANIMATIONS)

    def resolve_defaults(self) -> list[dict[str, Any]]:
        return self.resolve_standard_idles()
