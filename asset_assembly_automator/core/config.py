from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from asset_assembly_automator.core.paths import expand_path, migrate_legacy_app_data


def _expand_path(value: str) -> Path:
    return expand_path(value)


def _expand_config_paths(data: dict[str, Any]) -> dict[str, Any]:
    paths = data.get("paths")
    if isinstance(paths, dict):
        for key in ("app_data", "user_config", "secrets"):
            val = paths.get(key)
            if isinstance(val, str):
                paths[key] = str(expand_path(val))
    return data


class RemeshTargetTris(BaseSettings):
    hero: int = 300000
    npc: int = 300000
    crowd: int = 300000


class I2dTargetPolycount(BaseSettings):
    hero: int = 300000
    npc: int = 300000
    crowd: int = 300000


class MagnificSettings(BaseSettings):
    base_url: str = "https://api.magnific.com"
    mystic_model: str = "super_real"
    resolution: str = "2k"
    aspect_ratio: str = "portrait_2_3"
    upscale_mode: str = "precision_v2"
    upscale_scale_factor: str = "2x"
    upscale_flavor: str = "sublime"
    precision_sharpen: int = 7
    precision_smart_grain: int = 7
    precision_ultra_detail: int = 30
    max_concurrent_jobs: int = 2
    default_enabled: bool = True


class AgentCliSettings(BaseSettings):
    provider: Literal["cursor", "claude"] = "cursor"
    claude_command: str = "claude"
    claude_model: str = ""
    claude_extra_args: list[str] = Field(default_factory=list)


class UnityMcpSettings(BaseSettings):
    bridge: Literal["anklebreaker", "coplay", "official"] = "anklebreaker"


class MeshySettings(BaseSettings):
    base_url: str = "https://api.meshy.ai"
    ai_model: str = "meshy-7"
    model_type: str = "standard"
    default_preset: Literal["quality", "game_ready"] = "quality"
    default_texture_resolution: Literal["2k", "4k", "8k"] = "8k"
    ultra_mode: bool = False
    smart_topology: Literal["auto", "off", "lowpoly"] = "auto"
    i2d_target_formats: list[str] = Field(default_factory=lambda: ["fbx", "glb"])
    pose_mode: str = "t-pose"
    topology: str = "quad"
    enable_pbr: bool = True
    should_texture: bool = True
    hd_texture: bool = True
    should_remesh: bool = False
    target_polycount: int = 300000
    target_formats: list[str] = Field(default_factory=lambda: ["fbx"])
    image_enhancement: bool = True
    remove_lighting: bool = True
    rig_height_meters: float = 1.7
    hard_rig_face_limit: int = 300000
    i2d_target_polycount: I2dTargetPolycount = Field(default_factory=I2dTargetPolycount)
    remesh_target_tris: RemeshTargetTris = Field(default_factory=RemeshTargetTris)
    animation_fps: int = 30
    include_basic_animations_in_package: bool = True
    default_custom_animations: list[str] = Field(
        default_factory=lambda: ["idle3", "idle4", "idle12"]
    )
    multi_view: bool = False
    max_concurrent_jobs: int = 2
    i2d_max_image_px: int = 4096
    i2d_max_image_mb: int = 18
    use_hires_texture_image: bool = False


class HiggsfieldSettings(BaseSettings):
    provider: str = "mcp"
    mcp_url: str = "https://mcp.higgsfield.ai/mcp"
    oauth_redirect_uri: str = "http://localhost:8787/callback"
    oauth_timeout_seconds: int = 300
    api_base_url: str = "https://platform.higgsfield.ai"
    default_image_model: str = "soul_2"
    turnaround_model: str = "nano_banana_pro"
    aspect_ratio: str = "2:3"


class MidjourneySettings(BaseSettings):
    watch_folder: str = ""
    default_version: str = "6.1"
    default_aspect: str = "2:3"


class GuiSettings(BaseSettings):
    theme: str = "dark"
    show_getting_started: bool = True
    show_whats_new: bool = True


class WatcherSettings(BaseSettings):
    debounce_seconds: float = 1.5
    stability_checks: int = 3


class CursorCliSettings(BaseSettings):
    enabled: bool = True
    command: str = "cursor-agent"
    model: str = ""
    extra_args: list[str] = Field(default_factory=list)
    timeout_seconds: int = 900


class PathSettings(BaseSettings):
    app_data: Path = Field(
        default_factory=lambda: expand_path("%LOCALAPPDATA%/AssetAssemblyAutomator")
    )
    user_config: Path = Field(
        default_factory=lambda: expand_path("%USERPROFILE%/.asset_assembly_automator/config.yaml")
    )
    secrets: Path = Field(
        default_factory=lambda: expand_path("%USERPROFILE%/.asset_assembly_automator/secrets.env")
    )

    @field_validator("app_data", "user_config", "secrets", mode="before")
    @classmethod
    def _expand_path_fields(cls, value: Any) -> Path:
        if value is None:
            raise ValueError("path must not be None")
        return expand_path(value)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AAA_", extra="ignore")

    name: str = "Asset Assembly Automator"
    version: str = "0.2.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app: AppSettings = Field(default_factory=AppSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    meshy: MeshySettings = Field(default_factory=MeshySettings)
    magnific: MagnificSettings = Field(default_factory=MagnificSettings)
    higgsfield: HiggsfieldSettings = Field(default_factory=HiggsfieldSettings)
    midjourney: MidjourneySettings = Field(default_factory=MidjourneySettings)
    gui: GuiSettings = Field(default_factory=GuiSettings)
    watchers: WatcherSettings = Field(default_factory=WatcherSettings)
    cursor_cli: CursorCliSettings = Field(default_factory=CursorCliSettings)
    agent_cli: AgentCliSettings = Field(default_factory=AgentCliSettings)
    unity_mcp: UnityMcpSettings = Field(default_factory=UnityMcpSettings)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]
    default_path = repo_root / "config" / "default.yaml"
    merged: dict[str, Any] = _load_yaml(default_path)
    user_path = expand_path("%USERPROFILE%/.asset_assembly_automator/config.yaml")
    user_data = _load_yaml(user_path)
    for key, value in user_data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    merged = _expand_config_paths(merged)
    settings = Settings.model_validate(merged)
    migrate_legacy_app_data(settings.paths.app_data)
    return settings


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
