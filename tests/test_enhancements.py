from asset_assembly_automator.clients.meshy_client import MeshyClient
from asset_assembly_automator.core.concurrency import (
    MAGNIFIC_STAGES,
    MESHY_STAGES,
    UNITY_STAGES,
    stage_semaphore,
    stage_uses_unity_lock,
)
from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.state_machine import StageId, next_stage, stage_order_for_kind
from asset_assembly_automator.stages._base import meshy_settings_for_pipeline
from asset_assembly_automator.workflow.unity_import_poll import (
    import_request_path,
    write_import_request,
)


def test_meshy_quality_payload():
    payload = MeshyClient._build_i2d_payload(
        {
            "ai_model": "meshy-7",
            "model_type": "standard",
            "texture_resolution": "8k",
            "target_polycount": 300000,
            "image_enhancement": True,
            "pose_mode": "t-pose",
        },
        image_url="data:image/png;base64,abc",
    )
    assert payload["ai_model"] == "meshy-7"
    assert payload["texture_resolution"] == "8k"
    assert "hd_texture" not in payload
    assert payload["should_remesh"] is False
    assert "remove_lighting" not in payload


def test_meshy_game_ready_payload():
    payload = MeshyClient._build_i2d_payload(
        {
            "model_type": "smart-topology",
            "target_polycount": 4000,
            "image_enhancement": False,
        },
        image_url="data:image/png;base64,abc",
    )
    assert payload["model_type"] == "smart-topology"
    assert payload["ai_model"] == "meshy-t2"
    assert payload["target_polycount"] == 4000
    assert "topology" not in payload


def test_vehicle_stage_order_skips_rig():
    order = stage_order_for_kind("vehicle")
    assert StageId.MESHY_RIG not in order
    assert StageId.MESHY_ANIMATE not in order
    assert StageId.MAGNIFIC_UPREZ in order
    assert next_stage(StageId.MESHY_REMESH, asset_kind="vehicle") == StageId.MESHY_DOWNLOAD


def test_concurrency_stage_groups():
    assert stage_semaphore(StageId.MESHY_I2D) is not None
    assert stage_semaphore(StageId.MAGNIFIC_UPREZ) is not None
    assert stage_semaphore(StageId.IMAGE_PREP) is None
    assert StageId.MESHY_I2D in MESHY_STAGES
    assert StageId.MAGNIFIC_UPREZ in MAGNIFIC_STAGES
    assert stage_uses_unity_lock(StageId.UNITY_IMPORT)
    assert StageId.UNITY_IMPORT in UNITY_STAGES


def test_meshy_settings_for_pipeline_presets(tmp_path):
    db = Database(db_path=tmp_path / "test.db")
    project_id = db.create_project("P", str(tmp_path / "out"))
    pipeline_id = db.create_pipeline(
        project_id,
        "Test",
        asset_kind="vehicle",
        metadata={"meshy_preset": "game_ready", "smart_topology_polycount": 8000},
    )
    pipe = db.get_pipeline(pipeline_id)
    cfg = meshy_settings_for_pipeline(pipe)
    assert cfg["model_type"] == "smart-topology"
    assert cfg["target_polycount"] == 8000
    assert "pose_mode" not in cfg


def test_import_request_json(tmp_path):
    asset_root = tmp_path / "Assets" / "Characters" / "hero"
    asset_root.mkdir(parents=True)
    path = write_import_request(asset_root, slug="hero", asset_kind="character")
    assert path.is_file()
    assert import_request_path(asset_root).is_file()
