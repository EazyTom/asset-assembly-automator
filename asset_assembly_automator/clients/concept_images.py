from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def is_valid_image(path: str | Path) -> bool:
    p = Path(path)
    if not p.exists() or p.stat().st_size < 64:
        return False
    try:
        with Image.open(p) as img:
            img.verify()
        with Image.open(p) as img:
            img.load()
        return True
    except Exception:
        return False


def write_placeholder_png(
    path: Path,
    *,
    title: str,
    subtitle: str = "",
    size: tuple[int, int] = (768, 1152),
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color=(36, 40, 58))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, size[0], size[1]), outline=(80, 90, 120), width=3)
    draw.text((24, 24), title, fill=(220, 225, 235))
    if subtitle:
        draw.text((24, 56), subtitle, fill=(148, 163, 184))
    img.save(path, format="PNG")
    return path


async def download_image_url(
    url: str,
    dest: Path,
    *,
    client: httpx.AsyncClient | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    http = client or httpx.AsyncClient(timeout=120.0, follow_redirects=True)
    try:
        resp = await http.get(url)
        resp.raise_for_status()
        content = resp.content
        if not content.startswith(PNG_SIGNATURE) and not content.startswith(b"\xff\xd8\xff"):
            raise ValueError(f"Downloaded content from {url} is not a PNG/JPEG image")
        dest.write_bytes(content)
        if not is_valid_image(dest):
            raise ValueError(f"Downloaded file is not a valid image: {dest}")
        return dest
    finally:
        if own_client:
            await http.aclose()


def extract_image_urls(item: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    nested = item.get("results")
    if isinstance(nested, dict):
        for key in ("rawUrl", "minUrl", "thumbnailUrl"):
            val = nested.get(key)
            if isinstance(val, str) and val.startswith("http"):
                urls.append(val)
        raw = nested.get("raw")
        if isinstance(raw, dict) and raw.get("url"):
            urls.append(str(raw["url"]))
    for key in ("rawUrl", "image_url", "url"):
        val = item.get(key)
        if isinstance(val, str) and val.startswith("http"):
            urls.append(val)
    return urls


async def persist_concept_item(
    item: dict[str, Any],
    output_dir: Path,
    *,
    provider: str = "higgsfield",
    http: httpx.AsyncClient | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Resolve a generation result to a valid local PNG path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    job_id = str(item.get("id") or "concept")
    stem = f"concept_{provider}_{job_id[:8]}"
    dest = output_dir / f"{stem}.png"

    local = item.get("local_path")
    if isinstance(local, str) and local and not local.startswith("fake://"):
        local_path = Path(local)
        if is_valid_image(local_path):
            return local_path, {"source": "local_path", "job_id": job_id}

    for url in extract_image_urls(item):
        try:
            await download_image_url(url, dest, client=http)
            return dest, {"source": "url", "job_id": job_id, "url": url}
        except Exception as exc:
            last_error = str(exc)
    else:
        last_error = "No image URL in Higgsfield response"

    if isinstance(local, str) and local.startswith("fake://"):
        write_placeholder_png(
            dest,
            title="Dry-run concept",
            subtitle=item.get("params", {}).get("prompt", "")[:80],
        )
        return dest, {"source": "dry_run", "job_id": job_id}

        raise RuntimeError(
            f"Could not save concept image ({last_error}). "
            "Sign in to Higgsfield MCP on first run, or set HF_MCP_ACCESS_TOKEN / HF_CREDENTIALS."
        )
