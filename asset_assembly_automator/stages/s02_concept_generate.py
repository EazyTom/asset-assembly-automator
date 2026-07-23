from __future__ import annotations

import asyncio

from asset_assembly_automator.clients.concept_images import persist_concept_item
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import get_higgsfield_client, run_stage, stage_argparser


async def _run(ctx, db, dirs, writer):
    pipe = db.get_pipeline(ctx.pipeline_id)
    prompt = pipe.metadata.get("hf_prompt", "")
    if not prompt:
        prompts = db.conn.execute(
            "SELECT final_text FROM prompts WHERE pipeline_id = ? AND provider = 'higgsfield' ORDER BY id DESC LIMIT 1",
            (ctx.pipeline_id,),
        ).fetchone()
        prompt = prompts["final_text"] if prompts else pipe.asset_name

    settings = get_settings()
    client = get_higgsfield_client(ctx.dry_run, dirs["concept"])
    try:
        result = await client.generate_image(
            prompt,
            model=settings.higgsfield.default_image_model,
            count=1,
        )
        items = result.get("results", [])
        if not items:
            return StageResult(
                success=False,
                stage=StageId.CONCEPT_GENERATE.value,
                error="No results from Higgsfield",
            )

        saved = 0
        for item in items:
            try:
                if item.get("local_path"):
                    path = item["local_path"]
                    meta = item.get("download_meta") or {"source": "client"}
                else:
                    path_obj, meta = await persist_concept_item(
                        item, dirs["concept"], provider="higgsfield"
                    )
                    path = str(path_obj)
            except Exception as exc:
                writer.log("error", f"Failed to save concept image: {exc}")
                return StageResult(
                    success=False,
                    stage=StageId.CONCEPT_GENERATE.value,
                    error=str(exc),
                )

            asset_id = db.add_asset(
                ctx.pipeline_id,
                "concept",
                path,
                provider="higgsfield",
                thumb_path=path,
                metadata={
                    "job_id": item.get("id"),
                    "prompt": prompt,
                    **meta,
                },
            )
            saved += 1
            writer.log("info", "Concept saved", asset_id=asset_id, path=path)
    finally:
        if hasattr(client, "close"):
            await client.close()

    if saved == 0:
        return StageResult(
            success=False,
            stage=StageId.CONCEPT_GENERATE.value,
            error="No concept images saved",
        )

    return StageResult(
        success=True,
        stage=StageId.CONCEPT_GENERATE.value,
        message=f"Higgsfield concept generated ({saved} image(s))",
        next_stage=StageId.CONCEPT_REVIEW.value,
    )


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.CONCEPT_GENERATE.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    args = stage_argparser("Generate Higgsfield concept").parse_args()
    print(asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose)))
