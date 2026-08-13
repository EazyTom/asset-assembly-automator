import asyncio
from pathlib import Path

import pytest
from asset_assembly_automator.clients.cursor_cli_client import (
    CursorCliClient,
    FakeCursorCliClient,
    build_attached_prompt_cli_arg,
    resolve_subprocess_argv,
    stage_cursor_prompt_file,
)
from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.stages import s11_unity_import
from asset_assembly_automator.stages._base import bind_db, load_unity_import_template, unbind_db
from asset_assembly_automator.workflow.bootstrap import bootstrap_meshy_pipeline
from PIL import Image


@pytest.fixture
def workflow_db(tmp_path):
    database = Database(tmp_path / "workflow.db")
    unity_path = tmp_path / "UnityProject"
    unity_path.mkdir()
    out_root = tmp_path / "out"
    pid = database.create_project(
        "WorkflowProject",
        str(out_root),
        unity_project_path=str(unity_path),
    )
    return database, pid, unity_path, out_root


def _write_png(path: Path, size: tuple[int, int] = (64, 128)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(40, 120, 80)).save(path)


def test_load_unity_import_template():
    text = load_unity_import_template()
    assert "{character_slug}" in text
    assert "Unity MCP" in text
    assert "```csharp" in text
    assert "user-unity" in text
    assert "unity_execute_code" in text
    assert "CharacterManifestImportUtility" in text
    assert "SUCCESS" in text or "Prefab saved" in text
    assert "oval" in text.lower()


def test_load_unity_cleanup_template():
    from asset_assembly_automator.stages._base import load_unity_cleanup_template

    text = load_unity_cleanup_template()
    assert "{character_slug}" in text
    assert "PF_{character_slug}" in text
    assert "SUCCESS" in text
    assert "unity_execute_code" in text
    assert "Do not delete" in text
    assert (
        "GetComponentsInChildren" not in text
        or "FindObjectsOfTypeAll" in text
        or "resolveCharacterFolderPaths" in text
    )
    assert "deleteSlugScriptsInFolder" in text
    assert "Selected character only" in text or "selected character" in text.lower()


def test_render_unity_cleanup_template_substitutes_slug():
    from asset_assembly_automator.stages._base import load_unity_cleanup_template
    from asset_assembly_automator.workflow.unity_mcp_workflow import _render_workflow_template

    rendered = _render_workflow_template(
        load_unity_cleanup_template(),
        character_slug="river_scout",
        unity_project_path=r"C:\Unity\Meshy-Higgs-MCP",
        character_dir=r"C:\Unity\Meshy-Higgs-MCP\Assets\Characters\river_scout",
    )
    assert 'var slug = "river_scout"' in rendered
    assert "{character_slug}" not in rendered
    assert "remainingScene" in rendered


def test_render_unity_import_template_substitutes_slug():
    from asset_assembly_automator.workflow.unity_mcp_workflow import _render_workflow_template

    rendered = _render_workflow_template(
        load_unity_import_template(),
        character_slug="river_scout",
        unity_project_path=r"C:\Unity\Meshy-Higgs-MCP",
        character_dir=r"C:\Unity\Meshy-Higgs-MCP\Assets\Characters\river_scout",
        unity_import_zip=r"C:\Output\CHR_river_scout_UnityImport_v01.zip",
    )
    assert "PF_river_scout" in rendered
    assert "{character_slug}" not in rendered
    assert 'ImportFromSlug("river_scout")' in rendered


def test_compose_unity_mcp_prompts(workflow_db):
    from asset_assembly_automator.workflow.unity_mcp_workflow import (
        compose_cleanup_prompt,
        compose_import_prompt,
    )

    database, project_id, unity_path, _ = workflow_db
    prompt = compose_cleanup_prompt(
        asset_name="River Scout",
        character_slug="river_scout",
        unity_project_path=str(unity_path),
        character_dir=unity_path / "Assets" / "Characters" / "river_scout",
    )
    assert "Assets/Characters/river_scout" in prompt
    assert "PF_river_scout" in prompt
    assert 'var slug = "river_scout"' in prompt
    assert (
        "Cleanup succeeds only when unity_execute_code returns" in prompt
        or "execute_code returns" in prompt
    )
    assert "Selected character only" in prompt
    assert "resolveCharacterFolderPaths" in prompt

    import_prompt = compose_import_prompt(
        load_unity_import_template(),
        asset_name="River Scout",
        character_slug="river_scout",
        unity_project_path=str(unity_path),
        character_dir=unity_path / "Assets" / "Characters" / "river_scout",
        manifest_path=unity_path
        / "Assets"
        / "Characters"
        / "river_scout"
        / "unity_import_manifest.json",
        staged_files=["rig.fbx"],
        clips=[{"name": "Walk", "path": "walk.fbx", "type": "locomotion"}],
        unity_import_zip=unity_path.parent / "CHR_river_scout_UnityImport_v01.zip",
    )
    assert "oval" in import_prompt.lower()
    assert "PF_river_scout" in import_prompt
    assert 'ImportFromSlug("river_scout")' in import_prompt
    assert "user-unity" in import_prompt
    assert "walk.fbx" in import_prompt


@pytest.mark.asyncio
async def test_run_unity_cleanup_workflow_on_line_context(workflow_db):
    from asset_assembly_automator.workflow.unity_mcp_workflow import run_unity_cleanup_workflow

    database, project_id, unity_path, _ = workflow_db
    image = unity_path.parent / "drop.png"
    _write_png(image)
    pipeline_id = bootstrap_meshy_pipeline(database, project_id, "CleanupHero", image)
    contexts: list[dict] = []

    async def on_line(_level: str, _message: str, context: dict) -> None:
        contexts.append(context)

    result = await run_unity_cleanup_workflow(
        database,
        pipeline_id,
        dry_run=True,
        on_line=on_line,
    )
    assert result["success"] is True
    assert contexts
    assert all(isinstance(ctx, dict) for ctx in contexts)
    assert contexts[0]["provider"] == "unity_cleanup"


def test_bootstrap_meshy_pipeline(workflow_db, tmp_path):
    database, project_id, _, _ = workflow_db
    image = tmp_path / "hero.png"
    _write_png(image)
    pipeline_id = bootstrap_meshy_pipeline(
        database,
        project_id,
        "TestHero",
        image,
        poly_budget="npc",
        texture_prompt="game-ready character",
    )
    pipe = database.get_pipeline(pipeline_id)
    assert pipe is not None
    assert pipe.current_stage == StageId.IMAGE_PREP.value
    assert pipe.metadata.get("workflow") == "meshy_drop"
    assert pipe.metadata.get("character_slug") == "testhero"
    assert pipe.metadata.get("folder_slug") == "workflowproject-testhero"
    assert pipe.metadata.get("source_drop_path") == str(image.resolve())
    assert Path(pipe.metadata["source_image_path"]).exists()
    assets = database.get_assets(pipeline_id, "tpose")
    assert len(assets) == 1
    assert Path(assets[0]["file_path"]).exists()
    concepts = database.get_assets(pipeline_id, "concept")
    assert len(concepts) == 1


def test_bootstrap_reuses_pipeline_and_updates_image(workflow_db, tmp_path):
    database, project_id, _, _ = workflow_db
    image1 = tmp_path / "a.png"
    image2 = tmp_path / "b.png"
    _write_png(image1)
    _write_png(image2, size=(80, 160))
    pid1 = bootstrap_meshy_pipeline(database, project_id, "SameHero", image1)
    pid2 = bootstrap_meshy_pipeline(database, project_id, "SameHero", image2)
    assert pid1 == pid2
    pipe = database.get_pipeline(pid2)
    assert pipe.metadata["source_drop_path"] == str(image2.resolve())


@pytest.mark.asyncio
async def test_s11_unity_import_staging(workflow_db):
    database, project_id, unity_path, _ = workflow_db
    image = unity_path.parent / "drop.png"
    _write_png(image)
    pipeline_id = bootstrap_meshy_pipeline(
        database,
        project_id,
        "StageHero",
        image,
    )
    from asset_assembly_automator.core.output_paths import pipeline_output_slug
    from asset_assembly_automator.stages._base import get_output_dirs

    dirs = get_output_dirs(database, pipeline_id)
    dirs["source"].mkdir(parents=True, exist_ok=True)
    rig = dirs["source"] / "Character_output.fbx"
    walk = dirs["source"] / "Animation_Walking_withSkin.fbx"
    run = dirs["source"] / "Animation_Running_withSkin.fbx"
    for path in (rig, walk, run):
        path.write_bytes(b"FAKE_FBX")
    tex_dir = dirs["textures"]
    tex_dir.mkdir(parents=True, exist_ok=True)
    (tex_dir / "base_color.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    database.update_pipeline_stage(pipeline_id, StageId.COMPLETE.value, status="complete")

    token = bind_db(database)
    try:
        result = await s11_unity_import.run(pipeline_id, dry_run=True, verbose=False)
    finally:
        unbind_db(token)

    assert result.success
    pipe = database.get_pipeline(pipeline_id)
    slug = pipeline_output_slug(pipe)
    character_dir = unity_path / "Assets" / "Characters" / slug
    assert (character_dir / "Source" / rig.name).exists()
    assert (character_dir / "unity_import_manifest.json").exists()
    manifest = (character_dir / "unity_import_manifest.json").read_text(encoding="utf-8")
    assert "StageHero" in manifest
    assert '"no_scripts": false' in manifest.lower()
    assert '"default_animator_gait": 0' in manifest
    assert '"default_state": "Idle3"' in manifest
    assert '"Idle3"' in manifest
    assert '"aaa_helpers"' in manifest
    assert "com.assetassembly.import" in manifest
    assert '"Idle4"' in manifest
    assert '"Idle12"' in manifest


def test_resolve_subprocess_argv_windows_cmd(monkeypatch):
    monkeypatch.setattr("asset_assembly_automator.clients.cursor_cli_client.sys.platform", "win32")
    monkeypatch.setattr(
        "asset_assembly_automator.clients.cursor_cli_client.shutil.which",
        lambda _cmd: r"C:\Users\me\AppData\Local\cursor-agent\cursor-agent.CMD",
    )
    argv = resolve_subprocess_argv("cursor-agent", "status")
    assert argv == [
        "cmd.exe",
        "/c",
        r"C:\Users\me\AppData\Local\cursor-agent\cursor-agent.CMD",
        "status",
    ]


def test_resolve_subprocess_argv_unix(monkeypatch):
    monkeypatch.setattr("asset_assembly_automator.clients.cursor_cli_client.sys.platform", "linux")
    monkeypatch.setattr(
        "asset_assembly_automator.clients.cursor_cli_client.shutil.which",
        lambda _cmd: "/usr/local/bin/cursor-agent",
    )
    argv = resolve_subprocess_argv("cursor-agent", "-p", "hello")
    assert argv == ["/usr/local/bin/cursor-agent", "-p", "hello"]


@pytest.mark.asyncio
async def test_cursor_cli_format_stream_event_message():
    from asset_assembly_automator.clients.cursor_cli_client import format_stream_event_message

    started = format_stream_event_message(
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {
                "mcpToolCall": {
                    "args": {
                        "server": "user-unity",
                        "toolName": "unity_execute_code",
                        "arguments": {
                            "action": "execute",
                            "code": "return AssetDatabase.Refresh();",
                        },
                    }
                }
            },
        }
    )
    assert started is not None
    assert "Tool started" in started
    assert "unity_execute_code" in started
    assert "execute" in started

    completed = format_stream_event_message(
        {
            "type": "tool_call",
            "subtype": "completed",
            "tool_call": {
                "readToolCall": {
                    "result": {
                        "success": {
                            "content": "using UnityEngine;",
                            "totalLines": 12,
                        }
                    }
                }
            },
        }
    )
    assert completed is not None
    assert "Tool finished" in completed
    assert "read" in completed


@pytest.mark.asyncio
async def test_fake_cursor_cli_client():
    client = FakeCursorCliClient()
    health = await client.health_check()
    assert health["available"] is True
    lines: list[str] = []

    async def on_line(_level, message, _ctx):
        lines.append(message)

    result = await client.run_workflow("test prompt", cwd=".", on_line=on_line)
    assert result["success"] is True
    assert lines


def test_stage_cursor_prompt_file_uses_short_cli_arg(tmp_path):
    cwd = tmp_path / "unity"
    cwd.mkdir()
    character_dir = cwd / "Assets" / "Characters" / "robo"
    character_dir.mkdir(parents=True)
    long_prompt = "x" * 12000
    prompt_file = stage_cursor_prompt_file(
        long_prompt,
        cwd=cwd,
        name="unity_import_robo",
        prompt_dir=character_dir / ".aaa",
    )
    cli_arg = build_attached_prompt_cli_arg(prompt_file, cwd)
    assert prompt_file.exists()
    assert len(cli_arg) < 500
    assert "@Assets/Characters/robo/.aaa/unity_import_robo.md" in cli_arg
    assert prompt_file.read_text(encoding="utf-8") == long_prompt


@pytest.mark.asyncio
async def test_cursor_cli_run_workflow_mock_subprocess(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    class FakeStdout:
        def __init__(self) -> None:
            self._sent = False

        async def readline(self):
            if not self._sent:
                self._sent = True
                return b'{"type":"assistant","message":{"content":[{"text":"done"}]}}\n'
            return b""

    class FakeProc:
        def __init__(self) -> None:
            self.stdout = FakeStdout()
            self.returncode: int | None = None

        async def wait(self):
            self.returncode = 0
            return 0

    async def fake_exec(*args, **_kwargs):
        captured["argv"] = list(args)
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    client = CursorCliClient(command="cursor-agent")
    long_prompt = "Unity cleanup " + ("x" * 12000)
    result = await client.run_workflow(
        long_prompt,
        cwd=tmp_path,
        prompt_file_name="unity_cleanup_robo",
        prompt_dir=tmp_path / "Assets" / "Characters" / "robo" / ".aaa",
    )
    assert result["success"] is True
    assert "done" in result["final_text"]
    argv = captured["argv"]
    assert argv is not None
    cli_prompt = argv[-1]
    assert len(str(cli_prompt)) < 500
    assert "@Assets/Characters/robo/.aaa/unity_cleanup_robo.md" in str(cli_prompt)
    assert long_prompt not in str(cli_prompt)
    assert "--trust" in argv


def test_list_projects(workflow_db):
    database, project_id, _, _ = workflow_db
    projects = database.list_projects()
    assert any(p.id == project_id for p in projects)
    database.update_project(project_id, unity_project_path="C:/Games/MyUnity")
    updated = database.get_project(project_id)
    assert updated is not None
    assert updated.unity_project_path == "C:/Games/MyUnity"


def test_assess_meshy_asset_health_ok(workflow_db, tmp_path):
    from asset_assembly_automator.workflow.asset_health import assess_meshy_asset_health

    database, project_id, _, _ = workflow_db
    image = tmp_path / "hero.png"
    _write_png(image)
    pipeline_id = bootstrap_meshy_pipeline(database, project_id, "HealthyHero", image)
    health = assess_meshy_asset_health(database, pipeline_id)
    assert health.assets_present is True
    assert health.rerun_stage is None


def test_assess_meshy_asset_health_missing_deliverables(workflow_db, tmp_path):
    from asset_assembly_automator.core.output_paths import pipeline_output_slug
    from asset_assembly_automator.stages._base import get_output_dirs
    from asset_assembly_automator.workflow.asset_health import assess_meshy_asset_health

    database, project_id, _, _ = workflow_db
    image = tmp_path / "hero.png"
    _write_png(image)
    pipeline_id = bootstrap_meshy_pipeline(database, project_id, "MissingHero", image)
    dirs = get_output_dirs(database, pipeline_id)
    dirs["source"].mkdir(parents=True, exist_ok=True)
    rig = dirs["source"] / "Character_output.fbx"
    rig.write_bytes(b"FAKE_FBX")
    dirs["textures"].mkdir(parents=True, exist_ok=True)
    (dirs["textures"] / "base_color.png").write_bytes(b"PNG")
    zip_path = (
        dirs["root"]
        / f"CHR_{pipeline_output_slug(database.get_pipeline(pipeline_id))}_MeshyExport.zip"
    )
    zip_path.write_bytes(b"ZIP")
    database.update_pipeline_stage(
        pipeline_id,
        StageId.MESHY_QC.value,
        metadata={
            **database.get_pipeline(pipeline_id).metadata,
            "rig_task_id": "rig-123",
            "meshy_export_zip": str(zip_path),
            "primary_rig_fbx": str(rig),
        },
    )

    rig.unlink()
    (dirs["textures"] / "base_color.png").unlink()
    zip_path.unlink()

    health = assess_meshy_asset_health(database, pipeline_id)
    assert health.assets_present is False
    assert health.rerun_stage == StageId.MESHY_DOWNLOAD
    assert "rig_fbx" in health.missing


def test_assess_meshy_asset_health_missing_output_tree(workflow_db, tmp_path):
    from asset_assembly_automator.core.output_paths import character_output_root
    from asset_assembly_automator.workflow.asset_health import assess_meshy_asset_health

    database, project_id, _, _ = workflow_db
    image = tmp_path / "hero.png"
    _write_png(image)
    pipeline_id = bootstrap_meshy_pipeline(database, project_id, "GoneHero", image)
    database.update_pipeline_stage(
        pipeline_id,
        StageId.MESHY_QC.value,
        metadata={
            **database.get_pipeline(pipeline_id).metadata,
            "rig_task_id": "rig-123",
        },
    )

    import shutil

    project = database.get_project(project_id)
    pipe = database.get_pipeline(pipeline_id)
    assert project is not None and pipe is not None
    shutil.rmtree(character_output_root(project, pipe))

    health = assess_meshy_asset_health(database, pipeline_id)
    assert health.assets_present is False
    assert health.rerun_stage == StageId.IMAGE_PREP
    assert "output_folder" in health.missing


def test_assess_meshy_asset_health_missing_source(workflow_db, tmp_path):
    from asset_assembly_automator.workflow.asset_health import assess_meshy_asset_health

    database, project_id, _, _ = workflow_db
    image = tmp_path / "hero.png"
    _write_png(image)
    pipeline_id = bootstrap_meshy_pipeline(database, project_id, "NoSourceHero", image)
    pipe = database.get_pipeline(pipeline_id)
    Path(pipe.metadata["source_image_path"]).unlink()
    for row in database.get_assets(pipeline_id, "tpose"):
        Path(row["file_path"]).unlink(missing_ok=True)
    database.update_pipeline_stage(
        pipeline_id,
        pipe.current_stage,
        metadata={**pipe.metadata, "source_drop_path": str(tmp_path / "gone.png")},
    )

    health = assess_meshy_asset_health(database, pipeline_id)
    assert health.assets_present is False
    assert health.rerun_stage == StageId.IMAGE_PREP
    assert "source_image" in health.missing


def test_create_project_via_dialog_db(workflow_db, tmp_path):
    database, _, _, _ = workflow_db
    unity = tmp_path / "MyUnity"
    unity.mkdir()
    out = tmp_path / "CharsOut"
    pid = database.create_project(
        "Dialog Test",
        str(out),
        unity_project_path=str(unity),
    )
    project = database.get_project(pid)
    assert project is not None
    assert project.name == "Dialog Test"
    assert project.output_root == str(out)
    assert project.unity_project_path == str(unity)
