from pathlib import Path

from asset_assembly_automator.core.db.models import Database, local_database_path
from asset_assembly_automator.workflow.maintenance import (
    delete_character,
    delete_output_directory,
    delete_project,
    reset_application_database,
    validate_output_delete_path,
)


def test_validate_output_delete_path_rejects_placeholder():
    path = Path(r"C:\Output\demo-<character_slug>")
    assert validate_output_delete_path(path) is not None


def test_validate_output_delete_path_rejects_project_output_root(tmp_path):
    output_root = tmp_path / "AssetAssemblyAutomator" / "Output"
    output_root.mkdir(parents=True)
    assert validate_output_delete_path(output_root) is not None


def test_validate_output_delete_path_accepts_character_folder(tmp_path):
    target = tmp_path / "Output" / "demo_project-hero_npc"
    target.mkdir(parents=True)
    assert validate_output_delete_path(target) is None


def test_delete_output_directory(tmp_path):
    target = tmp_path / "Output" / "project-hero"
    target.mkdir(parents=True)
    (target / "Character_output.fbx").write_bytes(b"FBX")
    deleted = delete_output_directory(target)
    assert deleted == target.resolve()
    assert not target.exists()


def test_reset_application_database(tmp_path):
    db_path = tmp_path / "aaa.db"
    database = Database(db_path)
    project_id = database.create_project("Demo", str(tmp_path / "output"))
    pipeline_id = database.create_pipeline(project_id, "Hero")
    assert database.get_pipeline(pipeline_id) is not None

    path, fresh_db = reset_application_database(database)
    assert path == local_database_path(db_path)
    assert fresh_db.list_projects() == []
    assert fresh_db.get_pipeline(pipeline_id) is None


def test_delete_character_removes_output_and_db_rows(tmp_path):
    output_root = tmp_path / "Output"
    db = Database(tmp_path / "aaa.db")
    project_id = db.create_project("Demo Game", str(output_root))
    pipeline_id = db.create_pipeline(project_id, "Hero Knight")
    db.update_pipeline_stage(
        pipeline_id,
        "draft",
        metadata={"workflow": "meshy_drop", "character_slug": "hero_knight"},
    )
    db.add_log(pipeline_id, "info", "created")
    db.save_external_job(pipeline_id, "meshy", "task-1", "rigging")

    project = db.get_project(project_id)
    pipe = db.get_pipeline(pipeline_id)
    assert project is not None and pipe is not None
    folder = output_root / "demo_game-hero_knight"
    folder.mkdir(parents=True)
    (folder / "Character_output.fbx").write_bytes(b"FBX")

    result = delete_character(db, pipeline_id)

    assert result.asset_name == "Hero Knight"
    assert result.deleted_output_dirs == (folder.resolve(),)
    assert not folder.exists()
    assert db.get_pipeline(pipeline_id) is None
    assert db.get_logs_since(pipeline_id) == []
    assert db.get_external_job(pipeline_id, "rigging", active_only=False) is None


def test_delete_pipeline_cascade(tmp_path):
    db = Database(tmp_path / "aaa.db")
    project_id = db.create_project("Demo", str(tmp_path / "output"))
    pipeline_id = db.create_pipeline(project_id, "Hero")
    db.add_asset(pipeline_id, "tpose", str(tmp_path / "tpose.png"))
    db.record_stage(pipeline_id, "draft", "completed")

    assert db.delete_pipeline(pipeline_id) is True
    assert db.get_pipeline(pipeline_id) is None
    assert db.get_assets(pipeline_id) == []
    assert db.delete_pipeline(pipeline_id) is False


def test_delete_project_cascade(tmp_path):
    db = Database(tmp_path / "aaa.db")
    project_id = db.create_project("Demo Game", str(tmp_path / "output"))
    pipeline_a = db.create_pipeline(project_id, "Hero")
    pipeline_b = db.create_pipeline(project_id, "Villain")
    db.add_log(pipeline_a, "info", "hero log")
    db.save_external_job(pipeline_b, "meshy", "task-1", "rigging")

    result = delete_project(db, project_id)

    assert result.project_name == "Demo Game"
    assert result.pipeline_count == 2
    assert db.get_project(project_id) is None
    assert db.get_pipeline(pipeline_a) is None
    assert db.get_pipeline(pipeline_b) is None
    assert db.get_logs_since(pipeline_a) == []
    assert db.delete_project(project_id) is False
