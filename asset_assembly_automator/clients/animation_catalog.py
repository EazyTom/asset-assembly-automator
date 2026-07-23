from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from asset_assembly_automator.core.config import get_settings

CATALOG_URL = "https://api.meshy.ai/web/public/animations/resources"
# Walk/run are free with rig download; these idles are requested in meshy_animate (3 credits each).
STANDARD_IDLE_ANIMATIONS = ["idle3", "idle4", "idle12"]
DEFAULT_ANIMATIONS = [
    {"action_id": -1, "action_name": "Walking (rig free)", "is_default_included": True},
    {"action_id": -2, "action_name": "Running (rig free)", "is_default_included": True},
]


class AnimationCatalog:
    def __init__(self, cache_path: Path | None = None) -> None:
        settings = get_settings()
        self.cache_path = cache_path or (settings.paths.app_data / "animation_catalog.json")
        self._items: list[dict[str, Any]] = []

    async def sync(self, *, force: bool = False) -> list[dict[str, Any]]:
        if not force and self.cache_path.exists():
            mtime = datetime.fromtimestamp(self.cache_path.stat().st_mtime, tz=UTC)
            if datetime.now(UTC) - mtime < timedelta(days=1):
                self._items = json.loads(self.cache_path.read_text(encoding="utf-8"))
                return self._items
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(CATALOG_URL)
            resp.raise_for_status()
            data = resp.json()
        items = data if isinstance(data, list) else data.get("items", data.get("animations", []))
        normalized: list[dict[str, Any]] = []
        for item in items:
            normalized.append(
                {
                    "action_id": item.get("id") or item.get("action_id"),
                    "action_name": item.get("name") or item.get("action_name", ""),
                    "group": item.get("group", ""),
                    "category": item.get("category", ""),
                    "preview_url": item.get("preview_url", ""),
                }
            )
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
        self._items = normalized
        return normalized

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        if not self._items and self.cache_path.exists():
            self._items = json.loads(self.cache_path.read_text(encoding="utf-8"))
        q = query.lower()
        results = [
            i
            for i in self._items
            if q in (i.get("action_name") or "").lower() or q in (i.get("category") or "").lower()
        ]
        return results[:limit]

    def resolve_standard_idles(self) -> list[dict[str, Any]]:
        """Resolve idle3, idle4, idle12 from the Meshy animation catalog."""
        if not self._items and self.cache_path.exists():
            self._items = json.loads(self.cache_path.read_text(encoding="utf-8"))
        selections: list[dict[str, Any]] = []
        for query in STANDARD_IDLE_ANIMATIONS:
            matches = self.search(query, limit=5)
            picked = next(
                (m for m in matches if query in (m.get("action_name") or "").lower()),
                matches[0] if matches else None,
            )
            if picked and picked.get("action_id", 0) > 0:
                selections.append(
                    {
                        "action_id": picked["action_id"],
                        "action_name": picked["action_name"],
                        "is_default_included": True,
                    }
                )
        return selections

    def resolve_defaults(self) -> list[dict[str, Any]]:
        return self.resolve_standard_idles()
