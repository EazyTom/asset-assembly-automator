from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

# Meshy Workspace UI rejects uploads over 20 MB. API allows 100 MB, but we
# always stay under the UI cap so the same file works in both paths.
MESHY_I2D_HARD_LIMIT_BYTES = 20 * 1024 * 1024
_MIN_LONG_SIDE = 512


def validate_tpose_checklist(image_path: str) -> dict[str, Any]:
    """Heuristic T-pose checklist from workflow doc section 6."""
    path = Path(image_path)
    if not path.exists():
        return {"score": 0, "max": 10, "issues": ["File not found"], "passed": False}

    with Image.open(path) as img:
        w, h = img.size
        ratio = w / h if h else 0

    issues: list[str] = []
    score = 10

    if ratio < 0.4 or ratio > 0.85:
        issues.append("Aspect ratio not ideal for 2:3 character sheet")
        score -= 2
    if h < 512:
        issues.append("Resolution may be too low")
        score -= 1
    if w < 256:
        issues.append("Image may be cropped too narrowly")
        score -= 1

    return {
        "score": max(score, 0),
        "max": 10,
        "issues": issues,
        "passed": score >= 7,
        "width": w,
        "height": h,
        "aspect_ratio": round(ratio, 3),
    }


def crop_with_padding(image_path: str, output_path: str, *, padding: float = 0.05) -> str:
    path = Path(image_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(path) as img:
        img = img.convert("RGBA")
        bbox = img.getbbox()
        if bbox:
            left, top, right, bottom = bbox
            pw = int((right - left) * padding)
            ph = int((bottom - top) * padding)
            left = max(0, left - pw)
            top = max(0, top - ph)
            right = min(img.width, right + pw)
            bottom = min(img.height, bottom + ph)
            img = img.crop((left, top, right, bottom))
        img.save(out)
    return str(out)


def select_tpose_source(
    assets: list[dict[str, Any]], *, prefer_prepped: bool = False
) -> str | None:
    """Pick a T-pose file path from newest-first asset rows."""
    if not assets:
        return None
    if prefer_prepped:
        for asset in assets:
            path = str(asset.get("file_path") or "")
            if path and "_prepped" in Path(path).name:
                return path
    for asset in assets:
        path = str(asset.get("file_path") or "")
        if not path:
            continue
        name = Path(path).name.lower()
        if "_prepped" in name or "_cropped" in name:
            continue
        return path
    return str(assets[0].get("file_path") or "") or None


def _save_png(img: Image.Image, dest: Path) -> None:
    img.convert("RGBA").save(dest, format="PNG", optimize=True)


def _save_jpeg(img: Image.Image, dest: Path, *, quality: int) -> None:
    rgb = img.convert("RGB")
    rgb.save(dest, format="JPEG", quality=quality, optimize=True)


def downscale_to_budget(
    src: str,
    dest: str,
    *,
    max_px: int = 2048,
    max_bytes: int = 18 * 1024 * 1024,
) -> dict[str, Any]:
    """Resize/recompress so the file fits Meshy image-to-3D upload limits.

    Always enforces the 20 MB Meshy UI hard cap, even if ``max_bytes`` is higher.
    """
    src_path = Path(src)
    out_path = Path(dest)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = min(int(max_bytes), MESHY_I2D_HARD_LIMIT_BYTES)
    orig_bytes = src_path.stat().st_size if src_path.exists() else 0

    with Image.open(src_path) as img:
        working = img.convert("RGBA")
        orig_w, orig_h = working.size
        long_side = max(orig_w, orig_h)
        scale = 1.0
        if long_side > max_px:
            scale = min(scale, max_px / long_side)
        new_w = max(1, int(orig_w * scale))
        new_h = max(1, int(orig_h * scale))
        if (new_w, new_h) != (orig_w, orig_h):
            working = working.resize((new_w, new_h), Image.Resampling.LANCZOS)
        _save_png(working, out_path)

    needs_resize = (orig_w, orig_h) != (new_w, new_h) or out_path.stat().st_size > max_bytes

    if not needs_resize:
        return {
            "path": str(out_path),
            "downscaled": False,
            "original_width": orig_w,
            "original_height": orig_h,
            "final_width": orig_w,
            "final_height": orig_h,
            "original_bytes": orig_bytes,
            "final_bytes": out_path.stat().st_size,
            "format": "png",
        }

    for _ in range(8):
        size = out_path.stat().st_size
        if size <= max_bytes:
            break
        with Image.open(out_path) as img:
            w, h = img.size
            factor = (max_bytes / size) ** 0.5 * 0.9
            nw = max(_MIN_LONG_SIDE, int(w * factor))
            nh = max(_MIN_LONG_SIDE, int(h * factor))
            if nw >= w and nh >= h:
                nw = max(_MIN_LONG_SIDE, int(w * 0.85))
                nh = max(_MIN_LONG_SIDE, int(h * 0.85))
            if nw >= w and nh >= h:
                break
            resized = img.convert("RGBA").resize((nw, nh), Image.Resampling.LANCZOS)
            _save_png(resized, out_path)
            if min(nw, nh) <= _MIN_LONG_SIDE:
                break

    used_path = out_path
    used_format = "png"
    if used_path.stat().st_size > max_bytes:
        jpeg_path = out_path.with_suffix(".jpg")
        with Image.open(used_path) as img:
            rgb = img.convert("RGB")
            w, h = rgb.size
            for quality in (90, 80, 70, 60, 50):
                _save_jpeg(rgb, jpeg_path, quality=quality)
                if jpeg_path.stat().st_size <= max_bytes:
                    break
            for _ in range(4):
                if jpeg_path.stat().st_size <= max_bytes:
                    break
                w = max(_MIN_LONG_SIDE, int(w * 0.85))
                h = max(_MIN_LONG_SIDE, int(h * 0.85))
                rgb = rgb.resize((w, h), Image.Resampling.LANCZOS)
                _save_jpeg(rgb, jpeg_path, quality=70)
        if jpeg_path.stat().st_size <= used_path.stat().st_size:
            if used_path.exists() and used_path != jpeg_path:
                used_path.unlink(missing_ok=True)
            used_path = jpeg_path
            used_format = "jpeg"

    with Image.open(used_path) as final_img:
        final_w, final_h = final_img.size
    final_bytes = used_path.stat().st_size

    return {
        "path": str(used_path),
        "downscaled": True,
        "original_width": orig_w,
        "original_height": orig_h,
        "final_width": final_w,
        "final_height": final_h,
        "original_bytes": orig_bytes,
        "final_bytes": final_bytes,
        "format": used_format,
    }


def ensure_i2d_upload_image(
    src: str,
    dest: str,
    *,
    max_px: int,
    max_mb: int,
) -> dict[str, Any]:
    """No-op copy metadata when already within budget; otherwise downscale."""
    src_path = Path(src)
    max_bytes = min(int(max_mb) * 1024 * 1024, MESHY_I2D_HARD_LIMIT_BYTES)
    orig_bytes = src_path.stat().st_size if src_path.exists() else 0
    with Image.open(src_path) as img:
        orig_w, orig_h = img.size
    if max(orig_w, orig_h) <= max_px and orig_bytes <= max_bytes:
        return {
            "path": str(src_path),
            "downscaled": False,
            "original_width": orig_w,
            "original_height": orig_h,
            "final_width": orig_w,
            "final_height": orig_h,
            "original_bytes": orig_bytes,
            "final_bytes": orig_bytes,
            "format": src_path.suffix.lstrip(".").lower() or "png",
        }
    return downscale_to_budget(str(src_path), dest, max_px=max_px, max_bytes=max_bytes)
