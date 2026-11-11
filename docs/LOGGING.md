# Logging & debugging

Reference for inspecting pipeline logs and understanding what each layer captures. For agent guardrails, see the **Logging contract** section in [AGENTS.md](../AGENTS.md).

## Is it adequate for automatic phase debugging?

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

## Where logs live

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

## How to inspect logs (PowerShell)

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
