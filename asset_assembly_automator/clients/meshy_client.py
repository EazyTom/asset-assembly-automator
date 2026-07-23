from __future__ import annotations

import asyncio
import base64
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from asset_assembly_automator.clients.mesh_provider import MeshProvider
from asset_assembly_automator.clients.rig_provider import RigProvider
from asset_assembly_automator.core.secrets import meshy_api_key

ProgressCallback = Callable[[str], None]


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


class MeshyClient(MeshProvider, RigProvider):
    provider_name = "meshy"

    def __init__(self, api_key: str | None = None, base_url: str = "https://api.meshy.ai") -> None:
        self.api_key = api_key or meshy_api_key() or ""
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=120.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @retry(stop=stop_after_attempt(5), wait=wait_exponential_jitter(initial=1, max=30))
    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.post(path, json=payload)
        if resp.status_code == 429:
            resp.raise_for_status()
        resp.raise_for_status()
        data = resp.json()
        if "result" in data and isinstance(data["result"], str):
            return {"task_id": data["result"], "status": "PENDING"}
        return data

    @retry(stop=stop_after_attempt(5), wait=wait_exponential_jitter(initial=1, max=30))
    async def _get(self, path: str) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(path)
        resp.raise_for_status()
        return resp.json()

    def _encode_image(self, path: str) -> str:
        data = Path(path).read_bytes()
        ext = Path(path).suffix.lower().lstrip(".")
        mime = "jpeg" if ext in ("jpg", "jpeg") else "png"
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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ai_model": cfg.get("ai_model", "latest"),
            "model_type": cfg.get("model_type", "standard"),
            "enable_pbr": cfg.get("enable_pbr", True),
            "should_texture": cfg.get("should_texture", True),
            "hd_texture": cfg.get("hd_texture", True),
            "pose_mode": cfg.get("pose_mode", "t-pose"),
            "topology": cfg.get("topology", "quad"),
            "target_polycount": cfg.get("target_polycount", 300000),
            "target_formats": MeshyClient._i2d_target_formats(cfg),
            "image_enhancement": cfg.get("image_enhancement", True),
            "remove_lighting": cfg.get("remove_lighting", True),
        }
        if image_urls is not None:
            payload["image_urls"] = image_urls
        elif image_url is not None:
            payload["image_url"] = image_url
        if texture_image_url:
            payload["texture_image_url"] = texture_image_url
        elif texture_prompt:
            payload["texture_prompt"] = texture_prompt
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
            )
            return await self._post("/openapi/v1/multi-image-to-3d", payload)

        payload = self._build_i2d_payload(
            cfg,
            image_url=self._encode_image(image_path),
            texture_prompt=texture_prompt if not texture_image_url else None,
            texture_image_url=texture_image_url,
        )
        return await self._post("/openapi/v1/image-to-3d", payload)

    async def remesh(
        self,
        input_task_id: str,
        *,
        target_polycount: int,
        topology: str = "quad",
        target_formats: list[str] | None = None,
    ) -> dict[str, Any]:
        return await self._post(
            "/openapi/v1/remesh",
            {
                "input_task_id": input_task_id,
                "target_polycount": target_polycount,
                "topology": topology,
                "target_formats": target_formats or ["fbx"],
            },
        )

    async def rig(self, input_task_id: str, *, height_meters: float = 1.7) -> dict[str, Any]:
        return await self._post(
            "/openapi/v1/rigging",
            {"input_task_id": input_task_id, "height_meters": height_meters},
        )

    async def animate(self, rig_task_id: str, action_id: int, *, fps: int = 30) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "rig_task_id": rig_task_id,
            "action_id": action_id,
        }
        if fps:
            payload["post_process"] = {"operation_type": "change_fps", "fps": fps}
        return await self._post("/openapi/v1/animations", payload)

    async def get_task_status(self, task_id: str, task_type: str) -> dict[str, Any]:
        endpoints = {
            "image-to-3d": f"/openapi/v1/image-to-3d/{task_id}",
            "multi-image-to-3d": f"/openapi/v1/multi-image-to-3d/{task_id}",
            "remesh": f"/openapi/v1/remesh/{task_id}",
            "rigging": f"/openapi/v1/rigging/{task_id}",
            "animation": f"/openapi/v1/animations/{task_id}",
        }
        path = endpoints.get(task_type, f"/openapi/v1/image-to-3d/{task_id}")
        return await self._get(path)

    async def poll_until_done(
        self,
        task_id: str,
        task_type: str,
        *,
        timeout: float = 600,
        cancel_event: Any | None = None,
    ) -> dict[str, Any]:
        elapsed = 0.0
        delay = 5.0
        while elapsed < timeout:
            if cancel_event and getattr(cancel_event, "is_set", lambda: False)():
                raise asyncio.CancelledError("Polling cancelled")
            data = await self.get_task_status(task_id, task_type)
            status = data.get("status", "PENDING")
            if status in ("SUCCEEDED", "FAILED", "CANCELED"):
                return data
            await asyncio.sleep(delay)
            elapsed += delay
            delay = min(delay * 1.2, 30.0)
        raise TimeoutError(f"Task {task_id} timed out after {timeout}s")

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
            raise RuntimeError(f"Task {task_id} not succeeded: {data.get('status')}")

        result = data.get("result") or {}
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

        client = await self._get_client()
        dest = Path(save_to)
        dest.parent.mkdir(parents=True, exist_ok=True)
        downloaded: list[str] = []

        for name, url in urls.items():
            if not url:
                continue
            if task_type == "rigging":
                out = self._rigging_output_path(dest, name)
            elif len(urls) == 1:
                out = dest
            else:
                out = dest.parent / f"{dest.stem}_{name}{dest.suffix}"
            resp = await client.get(url)
            resp.raise_for_status()
            out.write_bytes(resp.content)
            downloaded.append(str(out))

        texture_urls = result.get("texture_urls") or []
        if include_textures and texture_urls:
            tex_dir = dest.parent / "Textures"
            tex_dir.mkdir(parents=True, exist_ok=True)
            for filename, url in _iter_texture_downloads(texture_urls):
                tex_path = tex_dir / filename
                resp = await client.get(url)
                resp.raise_for_status()
                tex_path.write_bytes(resp.content)
                downloaded.append(str(tex_path))

        return {"local_paths": downloaded, "urls": urls}

    async def _texture_urls_from_task(self, task_id: str, task_type: str) -> Any:
        data = await self.get_task_status(task_id, task_type)
        if data.get("status") != "SUCCEEDED":
            return []
        return (data.get("result") or {}).get("texture_urls") or []

    async def _download_texture_entries(
        self,
        client: httpx.AsyncClient,
        *,
        i2d_task_id: str | None,
        remesh_task_id: str | None,
        rig_fbx_path: Path | None,
        textures_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> tuple[list[tuple[str, Path]], str]:
        texture_urls: Any = []
        texture_source = "none"
        for source_label, task_id, task_type in (
            ("i2d", i2d_task_id, "image-to-3d"),
            ("remesh", remesh_task_id, "remesh"),
        ):
            if not task_id:
                continue
            urls = await self._texture_urls_from_task(task_id, task_type)
            if urls:
                texture_urls = urls
                texture_source = source_label
                break

        entries: list[tuple[str, Path]] = []
        if texture_urls:
            if progress:
                progress(f"Downloading PBR textures from Meshy ({texture_source})")
        for filename, url in _iter_texture_downloads(texture_urls):
            tex_path = textures_dir / filename
            resp = await client.get(url)
            resp.raise_for_status()
            tex_path.write_bytes(resp.content)
            entries.append((f"Textures/{filename}", tex_path))

        if entries:
            return entries, texture_source

        if rig_fbx_path and rig_fbx_path.is_file():
            if progress:
                progress("Extracting textures from rig FBX (API texture URLs unavailable)")
            extracted = _extract_textures_from_fbx(rig_fbx_path.read_bytes(), textures_dir)
            for path in extracted:
                entries.append((f"Textures/{path.name}", path))
            if extracted:
                texture_source = "rig_fbx"
        return entries, texture_source

    async def download_meshy_package(
        self,
        rig_task_id: str,
        *,
        i2d_task_id: str | None = None,
        remesh_task_id: str | None = None,
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
            raise RuntimeError(f"Rig task {rig_task_id} not succeeded: {rig_data.get('status')}")

        rig_result = rig_data.get("result") or {}
        source = Path(source_dir)
        textures = Path(textures_dir)
        source.mkdir(parents=True, exist_ok=True)
        textures.mkdir(parents=True, exist_ok=True)
        zip_file = Path(zip_path)
        zip_file.parent.mkdir(parents=True, exist_ok=True)

        entries: list[tuple[str, Path]] = []
        client = await self._get_client()

        rig_url = rig_result.get("rigged_character_fbx_url")
        rig_path: Path | None = None
        if rig_url:
            rig_name = _basename_from_url(rig_url, "Character_output.fbx")
            rig_path = source / rig_name
            _progress(f"Downloading rig FBX ({rig_name}) — large file, may take 1–2 minutes")
            resp = await client.get(rig_url)
            resp.raise_for_status()
            rig_path.write_bytes(resp.content)
            _progress(f"Rig FBX saved ({len(resp.content) // 1024} KB)")
            entries.append((f"Source/{rig_name}", rig_path))

        basic = rig_result.get("basic_animations") or {}
        for key in ("walking_fbx_url", "running_fbx_url"):
            url = basic.get(key)
            if not url:
                continue
            anim_name = _basename_from_url(url, f"{key}.fbx")
            anim_path = source / anim_name
            _progress(f"Downloading locomotion FBX ({anim_name})")
            resp = await client.get(url)
            resp.raise_for_status()
            anim_path.write_bytes(resp.content)
            entries.append((f"Source/{anim_name}", anim_path))

        texture_entries, texture_source = await self._download_texture_entries(
            client,
            i2d_task_id=i2d_task_id,
            remesh_task_id=remesh_task_id,
            rig_fbx_path=rig_path,
            textures_dir=textures,
            progress=progress,
        )
        entries.extend(texture_entries)

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
            raise RuntimeError(f"i2d task {task_id} not succeeded: {data.get('status')}")

        result = data.get("result") or {}
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

        client = await self._get_client()
        thumb_url = out["thumbnail_url"]
        if thumb_url:
            thumb_path = previews / "meshy_thumbnail.png"
            resp = await client.get(thumb_url)
            resp.raise_for_status()
            thumb_path.write_bytes(resp.content)
            out["thumbnail_path"] = str(thumb_path)

        model_urls = result.get("model_urls") or {}
        glb_url = model_urls.get("glb") if isinstance(model_urls, dict) else None
        if glb_url:
            glb_path = source / "Character_preview.glb"
            resp = await client.get(glb_url)
            resp.raise_for_status()
            glb_path.write_bytes(resp.content)
            out["glb_path"] = str(glb_path)

        texture_urls = result.get("texture_urls") or []
        if textures_dir and texture_urls:
            tex_root = Path(textures_dir)
            tex_root.mkdir(parents=True, exist_ok=True)
            for filename, url in _iter_texture_downloads(texture_urls):
                tex_path = tex_root / filename
                resp = await client.get(url)
                resp.raise_for_status()
                tex_path.write_bytes(resp.content)
                out["texture_paths"].append(str(tex_path))

        return out


class FakeMeshyClient(MeshyClient):
    """Offline fake for tests and --dry-run."""

    def __init__(self) -> None:
        super().__init__(api_key="fake")
        self._tasks: dict[str, dict[str, Any]] = {}

    async def close(self) -> None:
        pass

    def _make_task(self, task_type: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
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
        return self._make_task("image-to-3d", {"face_count": 320000})

    async def remesh(self, input_task_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._make_task("remesh", {"face_count": kwargs.get("target_polycount", 25000)})

    async def rig(self, input_task_id: str, **kwargs: Any) -> dict[str, Any]:
        return self._make_task("rigging")

    async def animate(self, rig_task_id: str, action_id: int, **kwargs: Any) -> dict[str, Any]:
        return self._make_task("animation", {"action_id": action_id})

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

    async def download_meshy_package(
        self,
        rig_task_id: str,
        *,
        i2d_task_id: str | None = None,
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
            "texture_source": "i2d",
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
