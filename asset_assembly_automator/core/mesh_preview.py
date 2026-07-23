"""Mesh preview cache and resolution for GUI (pre-rig textured mesh from Meshy i2d)."""

from __future__ import annotations

import shutil
from pathlib import Path

from asset_assembly_automator.clients.meshy_client import FakeMeshyClient, MeshyClient
from asset_assembly_automator.core.db.models import Pipeline
from asset_assembly_automator.core.logging import PipelineLogWriter
from asset_assembly_automator.core.output_paths import (
    pipeline_character_slug,
    preview_glb_path,
    preview_png_path,
)


def render_glb_preview_png(glb_path: Path, out_path: Path, *, size: int = 512) -> Path | None:
    """Optional tier-2 render via trimesh + pyrender when installed."""
    try:
        import numpy as np
        import pyrender
        import trimesh
    except ImportError:
        return None

    if not glb_path.is_file():
        return None

    try:
        scene = trimesh.load(glb_path, force="scene")
        if not isinstance(scene, trimesh.Scene):
            mesh = scene
            scene = trimesh.Scene(mesh)

        pr_scene = pyrender.Scene.from_trimesh_scene(scene, bg_color=[0.12, 0.12, 0.16, 1.0])
        camera = pyrender.PerspectiveCamera(yfov=np.pi / 3.0)
        camera_pose = np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 0.866, -0.5, 0.0],
                [0.0, 0.5, 0.866, 1.8],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        pr_scene.add(camera, pose=camera_pose)
        light = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=3.0)
        pr_scene.add(light, pose=camera_pose)

        renderer = pyrender.OffscreenRenderer(size, size)
        try:
            color, _ = renderer.render(pr_scene)
        finally:
            renderer.delete()

        from PIL import Image

        out_path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(color).save(out_path)
        return out_path
    except Exception:
        return None


def _copy_base_color_fallback(textures_dir: Path, out_path: Path) -> Path | None:
    for name in ("base_color.png", "basecolor.png"):
        candidate = textures_dir / name
        if candidate.is_file():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, out_path)
            return out_path
    return None


def ensure_mesh_preview(pipe: Pipeline, dirs: dict[str, Path]) -> Path | None:
    """Resolve cached preview PNG or regenerate from GLB / base_color fallback."""
    slug = pipeline_character_slug(pipe)
    png_path = preview_png_path(dirs, slug)

    meta_path = pipe.metadata.get("mesh_preview_path")
    if meta_path:
        path = Path(str(meta_path))
        if path.is_file():
            return path

    if png_path.is_file():
        return png_path

    glb_path = preview_glb_path(dirs)
    glb_meta = pipe.metadata.get("preview_glb_path")
    if glb_meta and Path(str(glb_meta)).is_file():
        glb_path = Path(str(glb_meta))

    rendered = render_glb_preview_png(glb_path, png_path)
    if rendered:
        return rendered

    textures_dir = dirs["textures"]
    fallback = _copy_base_color_fallback(textures_dir, png_path)
    if fallback:
        return fallback

    previews_textures = dirs["previews"] / "textures"
    return _copy_base_color_fallback(previews_textures, png_path)


async def cache_mesh_preview_from_i2d(
    client: MeshyClient | FakeMeshyClient,
    task_id: str,
    dirs: dict[str, Path],
    character_slug: str,
    *,
    writer: PipelineLogWriter | None = None,
) -> Path | None:
    """Download Meshy i2d preview assets and write the canonical preview PNG path."""
    assets = await client.download_i2d_preview_assets(
        task_id,
        previews_dir=dirs["previews"],
        source_dir=dirs["source"],
        textures_dir=dirs["textures"],
    )

    preview_path = preview_png_path(dirs, character_slug)
    preview_path.parent.mkdir(parents=True, exist_ok=True)

    source = "none"
    final_path: Path | None = None
    if assets.get("thumbnail_path"):
        shutil.copy2(assets["thumbnail_path"], preview_path)
        source = "thumbnail"
        final_path = preview_path
    elif assets.get("glb_path"):
        rendered = render_glb_preview_png(Path(assets["glb_path"]), preview_path)
        if rendered:
            source = "glb"
            final_path = rendered

    if final_path is None:
        fallback = _copy_base_color_fallback(dirs["textures"], preview_path)
        if fallback:
            source = "base_color"
            final_path = fallback

    if final_path and final_path.is_file():
        if writer:
            writer.log(
                "info",
                "Mesh preview cached",
                source=source,
                path=str(final_path),
                task_id=task_id,
            )
        return final_path

    if writer:
        writer.log(
            "warning",
            "Mesh preview not available from i2d task",
            task_id=task_id,
        )
    return None
