from __future__ import annotations

import os
from pathlib import Path

try:
    import keyring
except ImportError:  # pragma: no cover
    keyring = None  # type: ignore[assignment]

SERVICE_NAME = "asset-assembly-automator"


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def get_secret(key: str, default: str | None = None) -> str | None:
    env_val = os.environ.get(key)
    if env_val:
        return env_val
    if keyring is not None:
        try:
            val = keyring.get_password(SERVICE_NAME, key)
            if val:
                return val
        except Exception:
            pass
    from asset_assembly_automator.core.config import get_settings

    secrets_path = get_settings().paths.secrets
    secrets = _parse_env_file(secrets_path)
    if key in secrets:
        return secrets[key]
    repo_key = Path(__file__).resolve().parents[2] / "meshy-api.key"
    if key == "MESHY_API_KEY" and repo_key.exists():
        return repo_key.read_text(encoding="utf-8").strip()
    magnific_key = Path(__file__).resolve().parents[2] / "magnific-api.key"
    if key == "MAGNIFIC_API_KEY" and magnific_key.exists():
        return _parse_magnific_key_file(magnific_key)
    return default


def _parse_magnific_key_file(path: Path) -> str | None:
    """Read API key from legacy magnific-api.key (label + value lines)."""
    if not path.exists():
        return None
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    for i, line in enumerate(lines):
        if "api key" in line.lower() and i + 1 < len(lines):
            candidate = lines[i + 1].strip()
            if candidate and not candidate.endswith(":"):
                return candidate
    for line in lines:
        if line and not line.endswith(":") and "webhook" not in line.lower():
            if line.startswith("MS") or len(line) >= 20:
                return line
    return None


def set_secret(key: str, value: str) -> None:
    if keyring is not None:
        try:
            keyring.set_password(SERVICE_NAME, key, value)
            return
        except Exception:
            pass
    from asset_assembly_automator.core.config import get_settings

    secrets_path = get_settings().paths.secrets
    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _parse_env_file(secrets_path)
    existing[key] = value
    lines = [f"{k}={v}" for k, v in existing.items()]
    secrets_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def meshy_api_key() -> str | None:
    return get_secret("MESHY_API_KEY")


def higgsfield_credentials() -> str | None:
    combined = get_secret("HF_CREDENTIALS") or get_secret("HIGGSFIELD_CREDENTIALS")
    if combined and ":" in combined:
        return combined.strip()
    key = get_secret("HIGGSFIELD_API_KEY") or get_secret("HF_API_KEY")
    secret = get_secret("HIGGSFIELD_SECRET") or get_secret("HF_API_SECRET")
    if key and secret:
        return f"{key.strip()}:{secret.strip()}"
    return None


def magnific_api_key() -> str | None:
    return get_secret("MAGNIFIC_API_KEY")
