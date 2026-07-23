from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image


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


def downscale_to_budget(
    src: str,
    dest: str,
    *,
    max_px: int = 2048,
    max_bytes: int = 18 * 1024 * 1024,
) -> dict[str, Any]:
    """Resize PNG to fit Meshy image-to-3D upload limits when oversized."""
    src_path = Path(src)
    out_path = Path(dest)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(src_path) as img:
        img = img.convert("RGBA")
        orig_w, orig_h = img.size
        working = img.copy()

    orig_bytes = src_path.stat().st_size if src_path.exists() else 0
    long_side = max(orig_w, orig_h)
    needs_resize = long_side > max_px

    working.save(out_path, format="PNG", optimize=True)
    final_bytes = out_path.stat().st_size
    needs_resize = needs_resize or final_bytes > max_bytes

    if not needs_resize:
        return {
            "path": str(out_path),
            "downscaled": False,
            "original_width": orig_w,
            "original_height": orig_h,
            "final_width": orig_w,
            "final_height": orig_h,
            "original_bytes": orig_bytes,
            "final_bytes": final_bytes,
        }

    scale = 1.0
    if long_side > max_px:
        scale = min(scale, max_px / long_side)
    if final_bytes > max_bytes and final_bytes > 0:
        scale = min(scale, (max_bytes / final_bytes) ** 0.5 * 0.92)

    new_w = max(1, int(orig_w * scale))
    new_h = max(1, int(orig_h * scale))
    with Image.open(src_path) as img:
        resized = img.convert("RGBA").resize((new_w, new_h), Image.Resampling.LANCZOS)
        resized.save(out_path, format="PNG", optimize=True)

    # Second pass if still over byte budget
    for _ in range(4):
        size = out_path.stat().st_size
        if size <= max_bytes:
            break
        with Image.open(out_path) as img:
            w, h = img.size
            factor = (max_bytes / size) ** 0.5 * 0.9
            nw = max(1, int(w * factor))
            nh = max(1, int(h * factor))
            if nw >= w and nh >= h:
                break
            resized = img.convert("RGBA").resize((nw, nh), Image.Resampling.LANCZOS)
            resized.save(out_path, format="PNG", optimize=True)

    with Image.open(out_path) as final_img:
        final_w, final_h = final_img.size
    final_bytes = out_path.stat().st_size

    return {
        "path": str(out_path),
        "downscaled": True,
        "original_width": orig_w,
        "original_height": orig_h,
        "final_width": final_w,
        "final_height": final_h,
        "original_bytes": orig_bytes,
        "final_bytes": final_bytes,
    }
