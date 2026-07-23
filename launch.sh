#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "[AAA] Virtual env not found: .venv/bin/python" >&2
  echo >&2
  echo "Setup:" >&2
  echo "  python3 -m venv .venv" >&2
  echo "  .venv/bin/pip install -e ." >&2
  exit 1
fi

exec "$PY" -m asset_assembly_automator.gui.main
