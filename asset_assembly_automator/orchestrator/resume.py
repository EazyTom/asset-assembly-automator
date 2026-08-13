from __future__ import annotations

from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.state_machine import StageId


def find_resumable_pipelines(db: Database | None = None) -> list[dict]:
    db = db or Database()
    rows = db.conn.execute(
        """
        SELECT p.* FROM pipelines p
        WHERE p.status = 'active'
          AND p.current_stage NOT IN ('complete', 'draft', 'prompt_build', 'concept_review')
        ORDER BY p.updated_at DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_active_job(db: Database, pipeline_id: int, task_type: str) -> dict | None:
    return db.get_external_job(pipeline_id, task_type, active_only=True)


def should_regenerate(job: dict | None) -> bool:
    if not job:
        return True
    if job.get("status") in ("FAILED", "CANCELED"):
        return True
    expires = job.get("expires_at")
    if expires and job.get("status") == "SUCCEEDED":
        from datetime import UTC, datetime

        try:
            exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if exp < datetime.now(UTC):
                return True
        except ValueError:
            pass
    return False


STAGE_MODULE_MAP = {
    StageId.PROMPT_BUILD: "asset_assembly_automator.stages.s01_prompt_build",
    StageId.CONCEPT_GENERATE: "asset_assembly_automator.stages.s02_concept_generate",
    StageId.CONCEPT_REVIEW: "asset_assembly_automator.stages.s03_concept_review",
    StageId.MAGNIFIC_UPREZ: "asset_assembly_automator.stages.s04c_magnific_uprez",
    StageId.IMAGE_PREP: "asset_assembly_automator.stages.s04_image_prep",
    StageId.TURNAROUND: "asset_assembly_automator.stages.s04b_turnaround",
    StageId.MESHY_I2D: "asset_assembly_automator.stages.s05_meshy_image_to_3d",
    StageId.MESHY_REMESH: "asset_assembly_automator.stages.s06_meshy_remesh",
    StageId.MESHY_RIG: "asset_assembly_automator.stages.s07_meshy_rig",
    StageId.MESHY_ANIMATE: "asset_assembly_automator.stages.s08_meshy_animate",
    StageId.MESHY_DOWNLOAD: "asset_assembly_automator.stages.s09_meshy_download",
    StageId.MESHY_QC: "asset_assembly_automator.stages.s09b_qc_validate",
    StageId.PACKAGE_EXPORT: "asset_assembly_automator.stages.s10_package_export",
    StageId.UNITY_IMPORT: "asset_assembly_automator.stages.s11_unity_import",
}
