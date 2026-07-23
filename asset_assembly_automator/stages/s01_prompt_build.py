from __future__ import annotations

import asyncio
from pathlib import Path

from asset_assembly_automator.core.db.models import StageResult
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages._base import (
    load_template,
    render_prompt,
    run_stage,
    stage_argparser,
)


async def _run(ctx, db, dirs, writer):
    pipe = db.get_pipeline(ctx.pipeline_id)
    meta = dict(pipe.metadata or {})
    vars_ = ctx.extra.get("template_vars")
    if not vars_:
        vars_ = {
            "identity": str(meta.get("prompt_identity") or "").strip(),
            "style": str(meta.get("prompt_style") or "").strip(),
        }

    template_root = Path(__file__).resolve().parents[2] / "config" / "prompt_templates"
    mj_prompt = str(meta.get("mj_prompt") or "").strip()
    if not mj_prompt:
        mj_prompt = render_prompt(template_root / "midjourney_character.yaml", vars_)

    hf_data = load_template("higgsfield_character.yaml")
    hf_prompt = str(meta.get("hf_prompt") or "").strip()
    if not hf_prompt:
        hf_prompt = (
            hf_data["template"]
            .format(**{**hf_data.get("defaults", {}), **vars_})
            .replace("\n", " ")
            .strip()
        )

    meshy_prompt = str(meta.get("meshy_texture_prompt") or "").strip()
    if not meshy_prompt:
        meshy_prompt = (
            hf_data.get("meshy_texture_template", "")
            .format(extra_details=vars_.get("extra_details", ""))
            .replace("\n", " ")
            .strip()
        )

    db.save_prompt(
        ctx.pipeline_id,
        "midjourney",
        mj_prompt,
        template_id="midjourney_character_tpose",
        template_vars=vars_,
    )
    db.save_prompt(
        ctx.pipeline_id,
        "higgsfield",
        hf_prompt,
        template_id="higgsfield_character_tpose",
        template_vars=vars_,
    )
    db.save_prompt(
        ctx.pipeline_id, "meshy", meshy_prompt, template_id="meshy_texture", template_vars=vars_
    )

    meta.update(
        {
            "mj_prompt": mj_prompt,
            "hf_prompt": hf_prompt,
            "meshy_texture_prompt": meshy_prompt,
        }
    )
    db.update_pipeline_stage(ctx.pipeline_id, StageId.PROMPT_BUILD.value, metadata=meta)
    return StageResult(
        success=True,
        stage=StageId.PROMPT_BUILD.value,
        message="Prompts built",
        next_stage=StageId.CONCEPT_GENERATE.value,
        data=meta,
    )


async def run(pipeline_id: int, *, dry_run: bool = False, verbose: bool = False, **kwargs):
    return await run_stage(
        pipeline_id, StageId.PROMPT_BUILD.value, _run, dry_run=dry_run, verbose=verbose
    )


if __name__ == "__main__":
    args = stage_argparser("Build prompts from templates").parse_args()
    result = asyncio.run(run(args.pipeline_id, dry_run=args.dry_run, verbose=args.verbose))
    print(result)
