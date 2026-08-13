import pytest
from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.pipeline_timing import rollup_pipeline_timing


@pytest.fixture
def timing_db(tmp_path):
    db = Database(tmp_path / "timing.db")
    project_id = db.create_project("TimingProject", str(tmp_path / "out"))
    pipeline_id = db.create_pipeline(project_id, "TimingHero")
    return db, pipeline_id


def test_record_stage_updates_same_row(timing_db):
    db, pipeline_id = timing_db
    stage_id = db.record_stage(pipeline_id, "meshy_i2d", "in_progress")
    db.record_stage(
        pipeline_id,
        "meshy_i2d",
        "completed",
        stage_row_id=stage_id,
        duration_ms=120_000,
    )
    row = db.conn.execute(
        "SELECT COUNT(*) AS c FROM pipeline_stages WHERE pipeline_id = ?",
        (pipeline_id,),
    ).fetchone()
    assert row["c"] == 1
    done = db.conn.execute(
        "SELECT duration_ms, status FROM pipeline_stages WHERE id = ?",
        (stage_id,),
    ).fetchone()
    assert done["status"] == "completed"
    assert done["duration_ms"] == 120_000


def test_rollup_pipeline_timing_after_stages(timing_db):
    db, pipeline_id = timing_db

    def _complete(stage: str, ms: int) -> None:
        sid = db.record_stage(pipeline_id, stage, "in_progress")
        db.record_stage(
            pipeline_id,
            stage,
            "completed",
            stage_row_id=sid,
            duration_ms=ms,
        )

    _complete("image_prep", 5_000)
    _complete("meshy_i2d", 600_000)
    _complete("meshy_rig", 180_000)
    _complete("unity_import", 45_000)

    stats = rollup_pipeline_timing(
        db,
        pipeline_id,
        unity_csharp_ms=12_000,
        trigger="unity_import",
    )
    assert stats["meshy_total_ms"] == 780_000
    assert stats["unity_stage_ms"] == 45_000
    assert stats["unity_csharp_ms"] == 12_000
    assert stats["stage_durations_json"]["meshy_i2d"] == 600_000

    stored = db.get_pipeline_timing_stats(pipeline_id)
    assert stored is not None
    assert stored["meshy_total_ms"] == 780_000
    assert stored["stage_durations"]["unity_import"] == 45_000

    pipe = db.get_pipeline(pipeline_id)
    assert pipe.metadata["timing_stats"]["meshy_total_ms"] == 780_000


def test_rollup_reads_legacy_metadata_duration(timing_db):
    db, pipeline_id = timing_db
    db.record_stage(
        pipeline_id,
        "meshy_download",
        "completed",
        metadata={"duration_ms": 90_000},
    )
    stats = rollup_pipeline_timing(db, pipeline_id)
    assert stats["meshy_total_ms"] == 90_000
