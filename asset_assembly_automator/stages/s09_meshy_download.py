from __future__ import annotations

import asyncio

from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.output_paths import chr_file_prefix, pipeline_output_slug
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import get_meshy_client, run_stage, stage_argparser


async def _run(ctx, db, dirs, writer):
    pipe = db.get_pipeline(ctx.pipeline_id)
    client = get_meshy_client(ctx.dry_run)
    downloaded: list[str] = []
    output_slug = pipeline_output_slug(pipe)
    try:
        rig_task_id = pipe.metadata.get("rig_task_id")
        if not rig_task_id:
            job = db.get_external_job(ctx.pipeline_id, "rigging", active_only=False)
            rig_task_id = job["task_id"] if job else None
        if not rig_task_id:
            return StageResult(
                success=False,
                stage=StageId.MESHY_DOWNLOAD.value,
                error="No rig task id for Meshy package download",
            )

        i2d_task_id = pipe.metadata.get("i2d_task_id")
        if not i2d_task_id:
            i2d_job = db.get_external_job(ctx.pipeline_id, "image-to-3d", active_only=False)
            i2d_task_id = i2d_job["task_id"] if i2d_job else None

        remesh_task_id = pipe.metadata.get("remesh_task_id")
        if not remesh_task_id:
            remesh_job = db.get_external_job(ctx.pipeline_id, "remesh", active_only=False)
            remesh_task_id = remesh_job["task_id"] if remesh_job else None

        zip_name = f"{chr_file_prefix(output_slug)}_MeshyExport.zip"
        zip_path = dirs["root"] / zip_name
        writer.log(
            "info",
            "Downloading Meshy export package",
            rig_task_id=rig_task_id,
            i2d_task_id=i2d_task_id,
            remesh_task_id=remesh_task_id,
            zip_path=str(zip_path),
        )
        package = await client.download_meshy_package(
            rig_task_id,
            i2d_task_id=i2d_task_id,
            remesh_task_id=remesh_task_id,
            source_dir=dirs["source"],
            textures_dir=dirs["textures"],
            zip_path=zip_path,
            progress=lambda msg: writer.log("info", msg),
        )
        writer.log(
            "info",
            "Meshy package textures resolved",
            texture_source=package.get("texture_source"),
        )
        for path in package.get("local_paths", []):
            downloaded.append(path)
            suffix = path.lower()
            if suffix.endswith(".fbx"):
                db.add_asset(
                    ctx.pipeline_id,
                    "fbx",
                    path,
                    provider="meshy",
                    metadata={"task_type": "rigging", "rig_task_id": rig_task_id},
                )
            elif suffix.endswith(".png"):
                db.add_asset(
                    ctx.pipeline_id,
                    "texture",
                    path,
                    provider="meshy",
                    metadata={"source": "meshy_package"},
                )
            elif suffix.endswith(".zip"):
                db.add_asset(
                    ctx.pipeline_id,
                    "zip",
                    path,
                    provider="meshy",
                    metadata={"kind": "meshy_export"},
                )

        anim_ids = pipe.metadata.get("animation_task_ids") or []
        clip_meta = pipe.metadata.get("animation_clips") or []
        clip_by_task = {
            str(item.get("task_id")): str(item.get("action_name") or "")
            for item in clip_meta
            if isinstance(item, dict) and item.get("task_id")
        }
        for i, task_id in enumerate(anim_ids):
            action_name = clip_by_task.get(str(task_id), f"custom_{i}")
            safe = "".join(ch if ch.isalnum() else "_" for ch in action_name.lower()).strip("_")
            if not safe:
                safe = f"custom_{i}"
            dest = dirs["animations"] / f"Animation_{safe}_withSkin.fbx"
            writer.log(
                "info",
                "Downloading idle animation",
                task_id=task_id,
                action_name=action_name,
                dest=str(dest),
            )
            dl = await client.download_model(
                task_id, "animation", fmt="fbx", save_to=str(dest), include_textures=False
            )
            for p in dl.get("local_paths", []):
                downloaded.append(p)
                db.add_asset(
                    ctx.pipeline_id, "fbx", p, provider="meshy", metadata={"animation": True}
                )

        pipe.metadata["downloaded_paths"] = downloaded
        pipe.metadata["meshy_export_zip"] = package.get("zip_path")
        pipe.metadata["primary_rig_fbx"] = package.get("primary_fbx")
        db.update_pipeline_stage(
            ctx.pipeline_id, StageId.MESHY_DOWNLOAD.value, metadata=pipe.metadata
        )
        return StageResult(
            success=bool(downloaded),
            stage=StageId.MESHY_DOWNLOAD.value,
            message=f"Downloaded Meshy package ({len(downloaded)} files)",
            next_stage=StageId.MESHY_QC.value,
            data={"paths": downloaded, "zip_path": package.get("zip_path")},
            error=None if downloaded else "No files downloaded",
        )
    finally:
        if hasattr(client, "close"):
            await client.close()


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.MESHY_DOWNLOAD.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    args = stage_argparser("Download Meshy assets").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
