# AGENTS.md — Asset Assembly Automator

Guardrails for AI agents and contributors working in this repository.

## Environment

- **Install**: `.venv\Scripts\pip.exe install -e ".[dev]"` from repo root.
- **Launch GUI**: `.\launch.bat`

## Architecture invariants

1. **Stages are the unit of work.** Each stage module exposes `async def run(pipeline_id, *, dry_run, verbose, **kwargs) -> StageResult`.
2. **SQLite is the source of truth** for pipeline state, external job IDs, prompts, assets, and logs. Use WAL mode; never bypass `Database` for pipeline mutations.
3. **Runner binds DB context** via `bind_db()` before stage execution so tests can use isolated temp databases.
4. **Manual gates** (`concept_review`, optional `mesh_review`) stop auto-run; GUI/CLI must explicitly advance. `meshy_retexture` is an on-demand stage at `mesh_review` and never advances the pipeline.
5. **Dry-run uses fakes** (`FakeMeshyClient`, `FakeHiggsfieldClient`) — no API credits in tests.

## Logging

See [docs/LOGGING.md](docs/LOGGING.md) for log locations, inspection snippets, and layer overview.

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
- Store Meshy/Higgsfield task IDs in `external_jobs` immediately after creation (Meshy: use `run_meshy_task()` in `_base.py` — it saves the job, polls, records `consumed_credits` / `task_error`, and re-creates transient failures).
- Never retry a Meshy create call yourself; `MeshyClient._create` already handles 429 and ambiguous timeouts / 5xx without double-charging.
- Use `ctx.dry_run` to select fake providers via `get_meshy_client()` / `get_higgsfield_client()`.
- Respect `ctx.force_new` to skip job reattachment when re-running.
- Log provider milestones with `writer.log()` (see [docs/ENHANCEMENTS.md](docs/ENHANCEMENTS.md) provider milestone backlog).

## Provider anti-assumptions

| Provider | Do NOT assume |
|----------|---------------|
| **Meshy (AAA Character)** | Single merged animated FBX — package rig + per-clip FBXs + textures |
| **Meshy (AAA Vehicle / AAA Aircraft)** | Rig or animation clips exist — package the i2d (or remeshed) FBX + textures only |
| **Meshy rig** | Walk/run are free in `basic_animations`; custom clips cost 3 credits each |
| **Meshy remesh** | Skipped when i2d face count is already within budget; otherwise remesh to configured target (default max 300k) before rig |
| **Meshy mesh source** | Downstream input is always the i2d mesh — use `mesh_source_for_pipeline()`; an approved retexture variant replaces it |
| **Meshy API** | Default is v1 (`meshy.api_version`). v2 reads `output` and `GET /openapi/v2/tasks/{id}`. Do not send removed v1 fields (`model_type`, `hd_texture`, `ultra_mode`, `remove_lighting`); v2 image-to-3D uses `texture_model`, retexture uses `texture_prompt` / `texture_image_url` and `uv_mode` |
| **Meshy retexture** | `meshy-7.1` works — Retexture rejects it; use `retexture_ai_model` (meshy-7). On v2 that value is sent as `texture_model` |
| **Meshy MCP (chat)** | Its tasks are tracked in SQLite — they are not; exploration only. The key lives in gitignored `.cursor/mcp.json` |
| **Higgsfield** | Platform REST by default — v1 live runs use **hosted MCP** (`https://mcp.higgsfield.ai/mcp`) via `McpHiggsfieldAdapter`; REST fallback when `higgsfield.provider: rest` |
| **Higgsfield auth** | Cursor plugin OAuth is separate from the GUI; first GUI run opens browser OAuth once; tokens in `mcp/higgsfield_oauth.json` |
| **Midjourney** | No API — manual generate + watch-folder import only |
| **Unity MCP** | **Default AnkleBreaker** (`unity` / user-unity); **Coplay** + **Official** fallbacks — Settings or `unity_mcp.bridge`; happy-path import is C# UPM package. **Never** run `Assets/Reimport All` — it reimports the whole project and can hang or crash the Editor; after package sync, script recompile is enough (optionally `Assets/Refresh`). Reimport single FBXs only via AAA import/builders. |
| **Blender/ARP** | Phase 2 fallback — requires live Blender GUI, not headless |

## Secrets

- Never commit API keys. Use keyring or `%USERPROFILE%\.asset_assembly_automator\secrets.env`.
- Legacy repo-root `meshy-api.key` is a gitignored fallback probed by `secrets.py`; prefer secrets env.
- Higgsfield MCP: OAuth via GUI sign-in, or optional `HF_MCP_ACCESS_TOKEN` in secrets. REST fallback: `HF_CREDENTIALS=KEY:SECRET`.
- Python package `mcp` stays on 1.x (`mcp>=1.28,<2`). `clients/higgsfield_mcp.py` uses v1 client APIs (`streamable_http_client`, `mcp.shared._httpx_utils`). Do not install mcp 2.x without migrating that module.
- Do not log full API keys or Authorization headers.

## Conventions

- Package name: `asset_assembly_automator`
- CLI entrypoints: `aaa`, `aaa-gui`, `aaa-workflow`
- Config layers: `config/default.yaml` → user YAML → env (`AAA_` prefix)
- Ruff line length: 100, target Python 3.11
- Status colors in GUI: see `gui/theme/theme.py` `STATUS_COLORS`

## Quality checks

- Run manually: `run_tests.bat` (ruff check, ruff format --check, pytest)
- Or: `.venv\Scripts\python.exe -m ruff check asset_assembly_automator tests`
- Or: `.venv\Scripts\python.exe -m pytest -q`

## Skills & references

- Workflow source doc: `midjourney_meshy_unity_mcp_character_workflow.md`
- Product spec: `ASSET-ASSEMBLY-AUTOMATOR.md`

## Phase 2 boundaries

Do not wire these to `PipelineRunner` without explicit scope:

- `world_concept`, `world_i2d`, `world_remesh`, `world_export`
- Blender MCP + Auto-Rig Pro fallback (`clients/blender_arp_client.py`)

GUI may show stubs; schema already reserves stage IDs.
