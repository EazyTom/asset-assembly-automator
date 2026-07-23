from asset_assembly_automator.core.output_paths import (
    character_name_slug,
    character_output_root,
    chr_file_prefix,
    display_name_from_filename,
    folder_output_slug,
    slugify_path_component,
)


def test_slugify_path_component():
    assert slugify_path_component("Flood Circuit") == "flood_circuit"
    assert slugify_path_component("Cyberpunk  Courier!!") == "cyberpunk_courier"
    assert " " not in slugify_path_component("long name with spaces")


def test_display_name_from_filename():
    name = display_name_from_filename(
        "FloodCircuit cyberpunk street courier d08ca372-3e6d-4791-ae6f-e6109c322cd6"
    )
    assert " " in name
    assert "d08ca372" not in name


def test_character_name_slug():
    assert character_name_slug("Cyberpunk Courier NPC") == "cyberpunk_courier_npc"
    assert " " not in character_name_slug("Cyberpunk Courier NPC")


def test_folder_output_slug(tmp_path):
    from asset_assembly_automator.core.db.models import Database

    database = Database(tmp_path / "test.db")
    pid = database.create_project("Flood Circuit", "/tmp/out")
    pipeline_id = database.create_pipeline(pid, "Cyberpunk Courier")
    pipe = database.get_pipeline(pipeline_id)
    project = database.get_project(pid)
    assert pipe is not None and project is not None
    assert folder_output_slug(project, pipe) == "flood_circuit-cyberpunk_courier"


def test_output_dir_layout(tmp_path):
    from asset_assembly_automator.core.db.models import Database
    from asset_assembly_automator.stages._base import get_output_dirs

    database = Database(tmp_path / "test.db")
    pid = database.create_project("Flood Circuit", str(tmp_path / "out"))
    pipeline_id = database.create_pipeline(pid, "Cyberpunk Courier")
    pipe = database.get_pipeline(pipeline_id)
    project = database.get_project(pid)
    assert pipe is not None and project is not None

    database.update_pipeline_stage(
        pipeline_id,
        pipe.current_stage,
        metadata={
            **pipe.metadata,
            "character_slug": "cyberpunk_courier",
            "folder_slug": "flood_circuit-cyberpunk_courier",
        },
    )
    pipe = database.get_pipeline(pipeline_id)
    assert pipe is not None

    dirs = get_output_dirs(database, pipeline_id)
    expected_root = character_output_root(project, pipe)
    assert dirs["root"] == expected_root
    assert dirs["root"].name == "flood_circuit-cyberpunk_courier"
    assert dirs["root"].parent == tmp_path / "out"
    assert " " not in str(dirs["root"])


def test_legacy_output_root_fallback(tmp_path):
    from asset_assembly_automator.core.db.models import Database

    database = Database(tmp_path / "test.db")
    pid = database.create_project("Flood Circuit", str(tmp_path / "out"))
    pipeline_id = database.create_pipeline(pid, "Cyberpunk Courier")
    pipe = database.get_pipeline(pipeline_id)
    project = database.get_project(pid)
    assert pipe is not None and project is not None

    legacy_slug = "chr_0001_cyberpunk_courier"
    legacy_root = tmp_path / "out" / "flood_circuit" / "Characters" / legacy_slug
    legacy_root.mkdir(parents=True)
    database.update_pipeline_stage(
        pipeline_id,
        pipe.current_stage,
        metadata={**pipe.metadata, "output_slug": legacy_slug},
    )
    pipe = database.get_pipeline(pipeline_id)
    assert pipe is not None
    assert character_output_root(project, pipe) == legacy_root


def test_chr_file_prefix_uses_character_slug():
    assert chr_file_prefix("cyberpunk_courier") == "CHR_cyberpunk_courier"
