# Pipeline timing & SQLite DBA review

## End-to-end timing (what dominates)

| Phase | Typical share | Already optimized in v0.2? |
|-------|---------------|----------------------------|
| **Meshy i2d poll** | 30–60 min (Quality 8K) | Partially — fbx-only default, optional remesh off |
| **Meshy rig + animate** | 10–30 min | Parallel Meshy jobs (semaphore=2); 3 idle clips = 9 credits |
| **Magnific uprez** | 1–5 min | Optional; parallel with other Magnific jobs |
| **Concept / manual gates** | Human wait | Not automatable |
| **Unity import (happy path)** | 30 s – 3 min | **Yes** — C# watcher, no LLM; UPM inject cached |
| **Unity repair (failure)** | 5–15 min | Agent + MCP only on validation failure |

**Verdict:** The pipeline is **not** fully optimized at the Meshy/API layer — that is inherent provider latency. Orchestration overhead is already lean (WAL SQLite, async stages, skip remesh, C# Unity path). Further wins are **product choices** (game-ready preset, fewer idle clips, skip Magnific) not more Python threading.

### Remaining optimization opportunities

1. **Meshy poll backoff** — tune client poll interval after `IN_PROGRESS` (trade responsiveness vs CPU).
2. **Skip duplicate GLB download** when only FBX is exported (verify download stage).
3. **UPM package inject** — skip copy when manifest hash unchanged (already partially done in `ensure_unity_import_package`).
4. **Parallel concept + prep** — limited; image_prep must finish before i2d.
5. **Increase `meshy.max_concurrent_jobs`** — only if Meshy account tier allows; default 2 is safe.
6. **Live timing feedback** — use `pipeline_timing_stats` (below) to pick preset-specific defaults after a few runs.

---

## What we track

### Per stage (`pipeline_stages`)

| Column | Purpose |
|--------|---------|
| `started_at` / `completed_at` | Wall timestamps per run |
| `duration_ms` | Stage wall time (Python `run_stage` wrapper) |
| `status` | `in_progress` → `completed` / `failed` / `skipped` |

v0.2.0+ **updates the same row** on completion (no duplicate in_progress + completed rows).

### Rollup after Unity import (`pipeline_timing_stats`)

Written when `unity_import` succeeds (`rollup_pipeline_timing` in `core/pipeline_timing.py`):

| Column | Meaning |
|--------|---------|
| `pipeline_wall_ms` | `now - pipelines.created_at` (includes manual waits) |
| `stage_total_ms` | Sum of latest per-stage `duration_ms` |
| `meshy_total_ms` | Sum of meshy_* stages |
| `concept_ms` | prompt/concept/image_prep/magnific_uprez |
| `unity_stage_ms` | Python `s11` including poll wait |
| `unity_csharp_ms` | Editor `AaaImportRunner` only (from result JSON) |
| `stage_durations_json` | Full breakdown `{stage_name: ms}` |

Also mirrored to `pipelines.metadata.timing_stats` for GUI/API reads.

### Logs (`log_entries.context_json`)

Every stage finish logs `duration_ms` + `stage_id`. Log viewer **Duration** column reads this.

---

## Inspect timing (PowerShell)

```powershell
.\.venv\Scripts\python.exe -c @"
import sqlite3, json
conn = sqlite3.connect(r'$env:LOCALAPPDATA\AssetAssemblyAutomator\aaa.db')
conn.row_factory = sqlite3.Row
pid = 1  # change me
for r in conn.execute('SELECT stage_name, status, duration_ms, started_at, completed_at FROM pipeline_stages WHERE pipeline_id=? ORDER BY id', (pid,)):
    print(dict(r))
row = conn.execute('SELECT * FROM pipeline_timing_stats WHERE pipeline_id=?', (pid,)).fetchone()
if row:
    d = dict(row)
    d['stage_durations_json'] = json.loads(d['stage_durations_json'])[:200] if d.get('stage_durations_json') else {}
    print('STATS', d)
"@
```

---

## DBA recommendations (SQLite)

### Schema health (current)

| Table | Role | Notes |
|-------|------|-------|
| `pipelines` | Source of truth for run state | `metadata_json` blob growing — OK for app scale |
| `pipeline_stages` | Append/update per stage run | Now has `duration_ms`; indexed |
| `pipeline_timing_stats` | 1:1 rollup per pipeline | Added v0.2.0 |
| `log_entries` | High volume | Consider retention policy |
| `external_jobs` | Meshy task IDs | No unique on `(pipeline_id, task_type)` — duplicates possible on force re-run |
| `assets` | File registry | Multiple rows per type OK |
| `settings` | KV | Fine |

### Indexes added (v0.2.0)

- `pipeline_stages(pipeline_id, id DESC)` — latest runs, timing rollup
- `pipeline_stages(pipeline_id, stage_name, id DESC)` — per-stage history
- `log_entries(stage_id)` — join logs to stage
- `assets(pipeline_id, asset_type)` — asset lookups

### Recommended follow-ups (not yet implemented)

1. **`log_entries` retention** — archive or prune rows older than N days / per pipeline after export (table can grow unbounded).
2. **`external_jobs` partial unique index** — one active job per `(pipeline_id, task_type)` to prevent duplicate poll rows on resume bugs.
3. **Normalize hot metadata** — move frequently queried keys (`meshy_preset`, `timing_stats`) to columns if GUI dashboards need SQL aggregates across pipelines.
4. **`pipeline_stages` archival** — for re-run heavy pipelines, move old rows to `pipeline_stage_history` or delete completed rows older than last successful import.
5. **ANALYZE** — run `ANALYZE` after large imports; WAL mode already enabled.
6. **Avoid JSON in WHERE** — keep filtering on columns; use `stage_durations_json` only for display.

### Anti-patterns avoided

- Python bypassing `Database` for mutations (AGENTS.md invariant)
- Storing timing only in logs (now duplicated in queryable columns)
- Duplicate stage rows per run (fixed with `stage_row_id` update)

---

## Related

- `docs/ENHANCEMENTS.md` — speed audit pre/post
- `AGENTS.md` — logging contract
- `asset_assembly_automator/core/pipeline_timing.py` — rollup implementation
