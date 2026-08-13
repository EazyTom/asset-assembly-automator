# AGENTS.md — Asset Assembly Automator

Guardrails for AI agents and contributors working in this repository.

## Environment

- **OS**: Windows + PowerShell only in terminal commands.
- **Python**: `.venv\Scripts\python.exe` and `.venv\Scripts\pip.exe` — never bare `python`/`pip`.
- **Install**: `.venv\Scripts\pip.exe install -e ".[dev]"` from repo root.
- **Launch GUI**: `.\launch.bat` (Windows) or `./launch.sh` (Linux).
- **Chain commands** with `;`, not `&&` or `||`.

## Architecture invariants

1. **Stages are the unit of work.** Each stage module exposes `async def run(pipeline_id, *, dry_run, verbose, **kwargs) -> StageResult`.
2. **SQLite is the source of truth** for pipeline state, external job IDs, prompts, assets, and logs. Use WAL mode; never bypass `Database` for pipeline mutations.
3. **Runner binds DB context** via `bind_db()` before stage execution so tests can use isolated temp databases.
4. **Manual gates** (`concept_review`) stop auto-run; GUI/CLI must explicitly advance.
5. **Dry-run uses fakes** (`FakeMeshyClient`, `FakeHiggsfieldClient`) — no API credits in tests.

## Logging & debugging

### Is it adequate for automatic phase debugging?

**Mostly yes for orchestration; partially for provider internals.**

| Layer | What you get | Good for |
|-------|----------------|----------|
| **`run_stage()` wrapper** | Start/finish/fail per stage; `format_stage_error()` unwraps `ExceptionGroup` | Knowing *which* phase failed and the root error string |
| **`log_entries` (SQLite)** | All `PipelineLogWriter` + GUI `log_event()` rows; filterable in GUI | Live debugging, resume context, agent queries |
| **`pipeline_stages`** | `stage_name`, `status`, `error_message`, timestamps | Stage history and last failure reason |
| **`pipeline.jsonl` on disk** | Unified JSONL under character output | Offline tail, shareable artifact, post-mortem |
| **Per-stage JSONL** | `{stage}_{timestamp}.jsonl` in same folder | Isolated stage dumps |
| **`external_jobs`** | Meshy/Higgsfield task IDs keyed by stage | Reattach, poll, credit audit |
| **structlog** | JSON to stderr when `--verbose` / runner verbose | CLI headless runs |

**Gaps agents should close when touching a stage:**

- Several stages only emit generic start/complete lines (s01, s03, s07–s10). Add `writer.log()` at provider boundaries: job created, poll status, download path, skip/reattach decisions.
- Higgsfield MCP: log OAuth start/success (not tokens), `generate_image` job IDs, and `job_status` poll outcomes.
- Meshy: log task_id immediately after submit (also store in `external_jobs`).
- `log_entries.stage_id` is usually unset; link to `pipeline_stages.id` when extending logging if you need FK joins.
- Runner does not write its own lines; GUI adds “Pipeline run started” / “Waiting at manual gate” via `PipelineController.log_event()`.

### Where logs live

Paths use expanded env vars (`%LOCALAPPDATA%`, `%USERPROFILE%` — expanded at config load).

| Location | Contents |
|----------|----------|
| `%LOCALAPPDATA%/AssetAssemblyAutomator/aaa.db` | SQLite: pipelines, stages, assets, prompts, `log_entries`, `external_jobs` |
| `%LOCALAPPDATA%/AssetAssemblyAutomator/logs/` | Fallback JSONL when no character output root yet |
| `{project.output_root}/Characters/{asset}/logs/{pipeline_id}/pipeline.jsonl` | Primary unified log (GUI **Open log folder**) |
| `{...}/logs/{pipeline_id}/{stage}_{timestamp}.jsonl` | Per-run stage file |
| `%LOCALAPPDATA%/AssetAssemblyAutomator/mcp/higgsfield_oauth.json` | Higgsfield MCP OAuth client/tokens (not pipeline logs) |

User secrets: `%USERPROFILE%\.asset_assembly_automator\secrets.env`  
User config: `%USERPROFILE%\.asset_assembly_automator\config.yaml`

### How to inspect logs (agents)

```powershell
# Recent errors for a pipeline (replace 1 with pipeline_id)
.\.venv\Scripts\python.exe -c @"
import sqlite3, json
conn = sqlite3.connect(r'$env:LOCALAPPDATA\AssetAssemblyAutomator\aaa.db')
conn.row_factory = sqlite3.Row
for r in conn.execute('SELECT id, level, message, context_json, created_at FROM log_entries WHERE pipeline_id=1 ORDER BY id DESC LIMIT 20'):
    print(r['created_at'], r['level'], r['message'], r['context_json'][:200] if r['context_json'] else '')
"@

# Stage failure history
.\.venv\Scripts\python.exe -c @"
import sqlite3
conn = sqlite3.connect(r'$env:LOCALAPPDATA\AssetAssemblyAutomator\aaa.db')
conn.row_factory = sqlite3.Row
for r in conn.execute('SELECT stage_name, status, error_message, completed_at FROM pipeline_stages WHERE pipeline_id=1 ORDER BY id DESC LIMIT 10'):
    print(dict(r))
"@
```

CLI: run any stage with `--verbose` for structlog JSON on stderr.  
GUI: select pipeline → **Pipeline Log** panel (level filter, search, auto-scroll).

### Logging contract for new code

1. **Stages** — always go through `run_stage()`; never call `db.add_log()` directly from stage logic unless there is no `writer` (prefer `writer.log(level, msg, **context)`).
2. **Structured context** — pass dict-friendly kwargs (`task_id`, `path`, `provider`, `job_id`); they land in `context_json` and JSONL.
3. **Secrets** — never log API keys, OAuth tokens, or `Authorization` headers.
4. **Errors** — raise or return `StageResult(success=False, error=...)`; let `format_stage_error()` flatten exception groups.
5. **GUI actions** — use `PipelineController.log_event()` for user-initiated events (create pipeline, cancel, artifact detected).

## Threading & async

- GUI uses **qasync** — asyncio event loop drives Qt; do not block the loop with sync HTTP or file I/O.
- Blocking work belongs in `gui/executor.py` ThreadPoolExecutor or native async clients (httpx).
- **watchdog** file callbacks run on a worker thread; `_emit` bridges to the Qt loop via `loop.call_soon_threadsafe`. GUI debounces flushes with a **QTimer** (not an asyncio task).
- SQLite connections are thread-local per path in `get_connection()`.

## Stage contract

Every stage should:

- Call `run_stage()` from `_base.py` for logging, DB stage records, and stage advancement.
- Return `StageResult(success, stage, message, next_stage=..., data=...)`.
- Store Meshy/Higgsfield task IDs in `external_jobs` immediately after creation.
- Use `ctx.dry_run` to select fake providers via `get_meshy_client()` / `get_higgsfield_client()`.
- Respect `ctx.force_new` to skip job reattachment when re-running.
- Log provider milestones with `writer.log()` (see **Logging & debugging** gaps).

## Provider anti-assumptions

| Provider | Do NOT assume |
|----------|---------------|
| **Meshy** | Single merged animated FBX; always package rig + per-clip FBXs + textures |
| **Meshy rig** | Walk/run are free in `basic_animations`; custom clips cost 3 credits each |
| **Meshy remesh** | Skipped when i2d face count is already within budget; otherwise remesh to configured target (default max 300k) before rig |
| **Higgsfield** | Platform REST by default — v1 live runs use **hosted MCP** (`https://mcp.higgsfield.ai/mcp`) via `McpHiggsfieldAdapter`; REST fallback when `higgsfield.provider: rest` |
| **Higgsfield auth** | Cursor plugin OAuth is separate from the GUI; first GUI run opens browser OAuth once; tokens in `mcp/higgsfield_oauth.json` |
| **Midjourney** | No API — manual generate + watch-folder import only |
| **Unity MCP** | **Default AnkleBreaker** (`unity` / user-unity); **Coplay** + **Official** fallbacks — Settings or `unity_mcp.bridge`; happy-path import is C# UPM package |
| **Blender/ARP** | Phase 2 fallback — requires live Blender GUI, not headless |

## Secrets

- Never commit API keys. Use keyring or `%USERPROFILE%\.asset_assembly_automator\secrets.env`.
- `meshy-api.key` in repo root is a legacy fallback — migrate to secrets and rotate exposed keys.
- Higgsfield MCP: OAuth via GUI sign-in, or optional `HF_MCP_ACCESS_TOKEN` in secrets. REST fallback: `HF_CREDENTIALS=KEY:SECRET`.
- Do not log full API keys or Authorization headers.

## Conventions

- Package name: `asset_assembly_automator`
- CLI entrypoints: `aaa`, `aaa-gui`
- Config layers: `config/default.yaml` → user YAML → env (`AAA_` prefix)
- Ruff line length: 100, target Python 3.11
- Status colors in GUI: see `gui/theme/theme.py` `STATUS_COLORS`

## Quality hooks

- `.cursor/hooks.json` runs ruff on edit and pytest on stop.
- Run manually: `.venv\Scripts\python.exe -m ruff check asset_assembly_automator tests`
- Run tests: `.venv\Scripts\python.exe -m pytest -q`

## Skills & references

- Workflow source doc: `midjourney_meshy_unity_mcp_character_workflow.md`
- Product spec: `ASSET-ASSEMBLY-AUTOMATOR.md`
- Plan (read-only): do not edit `.cursor/plans/auto_pipeline_architecture_*.plan.md`

## Phase 2 boundaries

Do not wire these to `PipelineRunner` without explicit scope:

- `world_concept`, `world_i2d`, `world_remesh`, `world_export`
- `unity_import`
- Blender MCP + Auto-Rig Pro fallback (`clients/blender_arp_client.py`)

GUI may show stubs; schema already reserves stage IDs.
