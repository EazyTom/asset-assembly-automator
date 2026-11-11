"""Retexture an existing Meshy mesh (on demand, usually while waiting at mesh_review).

Each run creates one variant: an ``external_jobs`` row of type ``retexture`` whose
metadata records the prompt/style image and a local thumbnail. Approving a variant at
mesh_review makes it the mesh that remesh/rig/download use.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from asset_assembly_automator.clients.meshy_client import (
    RETEXTURE_PROMPT_MAX_CHARS,
    describe_task_failure,
)
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import (
    get_meshy_client,
    meshy_settings_for_pipeline,
    run_meshy_task,
    run_stage,
    stage_argparser,
)


def _base_mesh_job(db, pipeline_id: int, input_task_id: str | None) -> dict | None:
    jobs = db.list_external_jobs(pipeline_id, ["image-to-3d"])
    if input_task_id:
        return next((j for j in jobs if j["task_id"] == input_task_id), None)
    return next((j for j in reversed(jobs) if j.get("status") == "SUCCEEDED"), None)


async def _run(ctx, db, dirs, writer):
    stage = StageId.MESHY_RETEXTURE.value
    pipe = db.get_pipeline(ctx.pipeline_id)
    prompt = str(ctx.extra.get("prompt") or "").strip()
    style_image = str(ctx.extra.get("style_image_path") or "").strip() or None
    if style_image and not Path(style_image).is_file():
        return StageResult(
            success=False, stage=stage, error=f"Style image not found: {style_image}"
        )
    if not prompt and not style_image:
        return StageResult(
            success=False, stage=stage, error="Enter a texture prompt or choose a style image"
        )
    if len(prompt) > RETEXTURE_PROMPT_MAX_CHARS:
        return StageResult(
            success=False,
            stage=stage,
            error=f"Prompt is {len(prompt)} characters; Meshy allows {RETEXTURE_PROMPT_MAX_CHARS}",
        )

    base = _base_mesh_job(db, ctx.pipeline_id, ctx.extra.get("input_task_id"))
    if not base:
        return StageResult(
            success=False,
            stage=stage,
            error="No finished image-to-3D mesh to retexture; run Meshy image-to-3D first",
        )

    cfg = meshy_settings_for_pipeline(pipe)
    writer.log(
        "info",
        "Retexture settings",
        input_task_id=base["task_id"],
        ai_model=cfg.get("retexture_ai_model"),
        enable_original_uv=cfg.get("retexture_enable_original_uv"),
        texture_resolution=cfg.get("texture_resolution"),
        prompt_chars=len(prompt),
        style_image=style_image,
    )
    client = get_meshy_client(ctx.dry_run)
    try:
        result = await run_meshy_task(
            client,
            db,
            ctx,
            writer,
            task_type="retexture",
            metadata={
                "input_task_id": base["task_id"],
                "prompt": prompt,
                "style_image_path": style_image,
            },
            create=lambda: client.retexture(
                base["task_id"],
                text_style_prompt=prompt or None,
                image_style_path=style_image,
                settings=cfg,
            ),
        )
        task_id = result["task_id"]
        # Retexture keeps the input geometry.
        if base.get("face_count"):
            db.update_external_job(result["job_id"], face_count=base["face_count"])
        if result.get("status") != "SUCCEEDED":
            return StageResult(
                success=False,
                stage=stage,
                error=f"Retexture {describe_task_failure(result)}",
                data={"task_id": task_id},
            )
        thumb = await client.download_task_thumbnail(
            task_id, "retexture", dirs["previews"] / "variants" / f"retexture_{task_id}.png"
        )
        if thumb:
            db.update_external_job(result["job_id"], metadata={"thumbnail_path": str(thumb)})
        return StageResult(
            success=True,
            stage=stage,
            message="Retexture variant ready — approve it at mesh review to use it",
            data={
                "task_id": task_id,
                "thumbnail_path": str(thumb) if thumb else None,
                "input_task_id": base["task_id"],
            },
        )
    finally:
        if hasattr(client, "close"):
            await client.close()


async def run(
    pipeline_id: int,
    *,
    dry_run: bool = False,
    verbose: bool = False,
    prompt: str | None = None,
    style_image_path: str | None = None,
    input_task_id: str | None = None,
    **kwargs,
):
    return await run_stage(
        pipeline_id,
        StageId.MESHY_RETEXTURE.value,
        _run,
        dry_run=dry_run,
        verbose=verbose,
        prompt=prompt,
        style_image_path=style_image_path,
        input_task_id=input_task_id,
    )


if __name__ == "__main__":
    parser = stage_argparser("Meshy retexture variant")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--style-image", default=None)
    args = parser.parse_args()
    print(
        asyncio.run(
            run(
                args.pipeline_id,
                dry_run=args.dry_run,
                verbose=args.verbose,
                prompt=args.prompt,
                style_image_path=args.style_image,
            )
        )
    )
