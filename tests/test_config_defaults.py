from asset_assembly_automator.core.config import get_settings


def test_default_idle_animations():
    assert get_settings().meshy.default_custom_animations == ["idle3", "idle4", "idle12"]


def test_default_meshy_preview_settings():
    meshy = get_settings().meshy
    assert meshy.smart_topology == "auto"
    assert meshy.i2d_target_formats == ["fbx", "glb"]


def test_default_include_basic_animations_in_package():
    assert get_settings().meshy.include_basic_animations_in_package is True


def test_default_magnific_settings():
    magnific = get_settings().magnific
    assert magnific.mystic_model == "super_real"
    assert magnific.resolution == "2k"
    assert magnific.upscale_mode == "precision_v2"


def test_default_meshy_i2d_image_limits():
    meshy = get_settings().meshy
    assert meshy.i2d_max_image_px == 4096
    assert meshy.i2d_max_image_mb == 18
    assert meshy.use_hires_texture_image is False
    assert meshy.api_version == "v1"
    assert meshy.texture_model == "meshy-7"
    assert meshy.ai_model == "meshy-7.1"
    assert meshy.geometry_resolution == "standard"
    assert meshy.smart_topology_model == "meshy-t2.5"
    assert meshy.retexture_ai_model == "meshy-7"
    assert meshy.poll_timeout_seconds == 3600
    assert meshy.mesh_review_gate is False


def test_default_unity_mcp_bridge():
    assert get_settings().unity_mcp.bridge == "anklebreaker"
