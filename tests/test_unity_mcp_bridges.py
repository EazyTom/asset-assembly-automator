from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.workflow.unity_mcp_bridges import (
    BRIDGES,
    compose_bridge_facts,
    resolve_unity_mcp_bridge,
)
from asset_assembly_automator.workflow.unity_mcp_workflow import compose_cleanup_prompt


def test_resolve_unity_mcp_bridge_default():
    bridge = resolve_unity_mcp_bridge()
    assert bridge.id == "anklebreaker"
    assert bridge.cursor_server_id == "user-unity"
    assert bridge.execute_code_tool == "unity_execute_code"


def test_resolve_unity_mcp_bridge_db_override(tmp_path):
    db = Database(tmp_path / "bridge.db")
    db.set_setting("unity_mcp_bridge", "coplay")
    bridge = resolve_unity_mcp_bridge(db=db)
    assert bridge.id == "coplay"
    assert bridge.execute_code_tool == "execute_code"


def test_compose_bridge_facts_lists_all_bridges():
    text = compose_bridge_facts()
    assert "user-unity" in text
    assert "user-unityMCP" in text
    assert "user-unity-mcp" in text


def test_compose_cleanup_prompt_uses_coplay_tools(tmp_path):
    db = Database(tmp_path / "cleanup.db")
    db.set_setting("unity_mcp_bridge", "coplay")
    prompt = compose_cleanup_prompt(
        asset_name="River Scout",
        character_slug="river_scout",
        unity_project_path=r"C:\Unity\Project",
        character_dir=tmp_path / "Assets" / "Characters" / "river_scout",
        db=db,
    )
    assert "execute_code" in prompt
    assert "user-unityMCP" in prompt
    assert BRIDGES["coplay"].label in prompt
