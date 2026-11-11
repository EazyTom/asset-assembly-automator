from __future__ import annotations

import logging
from enum import StrEnum

logger = logging.getLogger(__name__)

_DISPLAY_TO_VALUE = {
    "aaa character": "character",
    "aaa vehicle": "vehicle",
    "aaa aircraft": "aircraft",
    "character": "character",
    "vehicle": "vehicle",
    "aircraft": "aircraft",
}

_DISPLAY_LABELS = {
    "character": "AAA Character",
    "vehicle": "AAA Vehicle",
    "aircraft": "AAA Aircraft",
}

_DEFAULT_IMPORT_PROFILE = {
    "character": "character_humanoid",
    "vehicle": "vehicle_drive_dashboard",
    "aircraft": "aircraft_flight_cockpit",
}

_DEFAULT_TARGET_SIZE_METERS = {
    "character": 0.0,
    "vehicle": 4.2,
    "aircraft": 6.0,
}


class AssetKind(StrEnum):
    CHARACTER = "character"
    VEHICLE = "vehicle"
    AIRCRAFT = "aircraft"


class ImportProfile(StrEnum):
    CHARACTER_HUMANOID = "character_humanoid"
    AIRCRAFT_FLIGHT_COCKPIT = "aircraft_flight_cockpit"
    VEHICLE_DRIVE_DASHBOARD = "vehicle_drive_dashboard"
    STATIC_PROP = "static_prop"


def display_label(asset_kind: str) -> str:
    kind = normalize_asset_kind(asset_kind, strict=False)
    return _DISPLAY_LABELS.get(kind, _DISPLAY_LABELS["character"])


def normalize_asset_kind(value: str | None, *, strict: bool = False) -> str:
    """Map stored values or AAA display labels to canonical asset_kind."""
    if not value or not str(value).strip():
        if strict:
            raise ValueError("asset_kind is required")
        return AssetKind.CHARACTER.value

    key = str(value).strip().lower()
    if key in _DISPLAY_TO_VALUE:
        return _DISPLAY_TO_VALUE[key]

    if strict:
        raise ValueError(
            f"Unknown asset_kind {value!r}; expected AAA Character / AAA Vehicle / AAA Aircraft"
        )

    logger.warning("Unknown asset_kind %r; falling back to character", value)
    return AssetKind.CHARACTER.value


def default_import_profile(asset_kind: str) -> str:
    kind = normalize_asset_kind(asset_kind, strict=False)
    return _DEFAULT_IMPORT_PROFILE.get(kind, ImportProfile.CHARACTER_HUMANOID.value)


def default_target_size_meters(asset_kind: str) -> float:
    kind = normalize_asset_kind(asset_kind, strict=False)
    return _DEFAULT_TARGET_SIZE_METERS.get(kind, 0.0)
