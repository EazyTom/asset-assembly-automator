# AAA Enhancements — Character / Vehicle / Aircraft

Durable spec for the v0.2 enhancement track. See the implementation plan for full history.

## Status (v0.2.0)

**Legend:** ✅ **Complete** · 🔄 **In queue** · ⏸ **Deferred** (Phase 2 / out of scope)

### ✅ Complete

| Area | Delivered |
|------|-----------|
| **Asset kinds** | `character` / `vehicle` / `aircraft` on `pipelines`; branched stage graph (vehicles/aircraft skip rig/animate) |
| **Meshy presets** | Quality (`meshy-7`, 8K) vs Game-ready (`smart-topology`); GUI + config |
| **Remesh** | Optional; **default off**; skip when disabled |
| **Magnific** | Auto stage `magnific_uprez` **after concept approval** (preview native first) |
| **Concept intake** | Midjourney drop, Magnific, optional Higgsfield; only Meshy required for 3D |
| **Unity happy path** | UPM `com.assetassembly.import`; `import_request.json` → C# `AaaImportRunner` → `unity_import_result.json` |
| **Unity repair** | Agent CLI (Cursor/Claude) + `unity_import_repair.md` **only on validation failure** |
| **Unity MCP** | Default **AnkleBreaker** (`unity` / user-unity); **Coplay + Official fallbacks** (Settings / `unity_mcp.bridge`) |
| **Vehicle / aircraft** | Kind-specific import utilities, `DriveController` / `FlightController` |
| **Concurrency** | Meshy + Magnific semaphores; Unity import wait-queue (lock) |
| **Logging** | `duration_ms`, `stage_id` on stage rows + logs; Log viewer duration column |
| **Tools menu** | **Logs**, **Show errors**, **Diagnostics** (Meshy / Magnific / Unity MCP ping) |
| **Timing DB** | `pipeline_stages.duration_ms` (single row per run); `pipeline_timing_stats` rollup after successful import |
| **Workflow app** | Meshy Workflow: concept → Meshy → **Import to Unity** (`s11`) |
| **Unity workflows** | AnkleBreaker-aligned prompts: `unity_import.md`, `unity_import_cleanup.md`, `unity_import_repair.md` |
| **Tests** | pytest suite (asset kinds, remesh skip, Unity lock, s11 dry-run, MCP bridges, timing rollup) |
| **Docs** | README, AAA-WORKFLOW, ENHANCEMENTS, DB-TIMING, Getting Started / What's New v0.2 |

### 🔄 In queue

| Item | Notes |
|------|-------|
| **Live speed baseline** | Populate speed audit with real `pipeline_timing_stats` from first full Quality + Unity runs |
| **Timing UI** | Workflow/Command Center panel reading `pipeline_timing_stats` (DB ready; GUI not built) |
| **Command Center `unity_import`** | `s11` runnable from **Meshy Workflow app** only; not auto-chained from Command Center runner |
| **Provider milestone logs** | More `writer.log()` at Meshy/Higgsfield poll boundaries (AGENTS.md gaps: s01, s03, s07–s10) |
| **Meshy poll tuning** | Backoff / interval optimization after live timing data |
| **DB hygiene** | `log_entries` retention; unique active `external_jobs` per `(pipeline_id, task_type)` — see [DB-TIMING.md](DB-TIMING.md) |
| **Phase 2 stub copy** | Command Center Phase 2 tab still lists `unity_import` as Phase 2 (implementation moved to v0.2 Workflow app) |
| **End-to-end live validation** | Full run: Unity 6 + AnkleBreaker + open Editor + real Meshy credits |

### ⏸ Deferred (Phase 2 / v1 out of scope)

| Item | Notes |
|------|-------|
| **World pipeline** | `world_concept`, `world_i2d`, `world_remesh`, `world_export` — schema + GUI stub only |
| **Blender MCP + Auto-Rig Pro** | `clients/blender_arp_client.py` stub; not wired to runner |
| **Parallel Unity Editors** | Serialized by design (`unity_imports: 1`) |
| **Meshy TCP bridge** | Not planned v1 |
| **Python UnityMcpClient** | Agent CLI + MCP only |
| **Force remesh on every Quality job** | Remesh optional; default off |

---

## Goals

- **Asset kinds:** Character, Vehicle, Aircraft (not Worldbuilding in v1).
- **Meshy 7 Quality** vs **Game-ready Smart Topology** presets; optional remesh (default off).
- **Magnific auto-uprez** after concept approval (manual Uprez retained).
- **Predetermined C# Unity import** via UPM package; **AnkleBreaker MCP / cursor-agent only on validation failure**.
- **Parallel Meshy/Magnific**; **serialized Unity import** (wait-queue).
- **Structured logging** (`duration_ms`, task_id, skip reasons) + Tools → Logs / Diagnostics.

## Locked decisions

| Topic | Choice |
|-------|--------|
| Flying type | **Aircraft** (`asset_kind=aircraft`) |
| Remesh | Optional, default **off** — texturing is in `meshy_i2d`, not remesh |
| Unity happy path | `com.assetassembly.import` package + `import_request.json` → `unity_import_result.json` |
| Unity repair | Default **AnkleBreaker** `unity` / user-unity; Coplay + Official fallbacks via Settings / config |
| Unity version | **Unity 6** Editor required for `unity_import` |
| Unity package | Injected to `Packages/com.assetassembly.import/` — not loose `Assets/` copies |
| Magnific | Auto stage after approval (preview native concepts first) |
| Parallel Unity | **Never** — `unity_imports: 1` wait-queue |

## Meshy API notes

- **Quality:** `ai_model=meshy-7`, `texture_resolution=8k`, `should_remesh=false` on i2d.
- **Game-ready:** `model_type=smart-topology`, `ai_model=meshy-t2`, `target_polycount` 100–15000.
- No `remove_lighting` on meshy-7. 8K costs 15 credits.

## Unity import flow

1. Python injects UPM package, stages FBX/textures/manifest, acquires Unity lock.
2. Writes `{slug}/.aaa/import_request.json`.
3. Editor `AaaImportRunner` runs `ImportFromSlug` + `AssetAssemblyValidator`.
4. Python polls `{slug}/.aaa/unity_import_result.json`.
5. On failure only: agent CLI + `unity_import_repair.md` (AnkleBreaker `unity_*` tools), re-validate once.

## Required dependencies (Unity import)

| Item | Required |
|------|----------|
| Unity 6 Editor | Yes — project open during import |
| Unity MCP (one bridge) | Yes — default AnkleBreaker; Coplay/Official fallbacks for repair, cleanup, Diagnostics |
| Meshy API key | Yes — for Meshy stages before import |

**Default bridge:** AnkleBreaker (`unity` / user-unity). Override in **Settings → Unity MCP bridge** or `unity_mcp.bridge` in user config. See `mcp.json.example` — enable one Unity MCP server at a time.

## Speed audit (pre)

Baseline bottlenecks addressed in this release:

| Bottleneck | Fix |
|------------|-----|
| Remesh polls i2d when disabled | Immediate skip when `remesh_enabled=false` |
| i2d fbx+glb | Default fbx-only for pipeline |
| 2048px downscale after Magnific | Quality cap 4096px / **20 MB hard cap** (default 18 MB) |
| s11 always cursor-agent | C# watcher; agent only on fail |
| max_concurrent_jobs unused | Provider semaphores wired |

## Speed audit (post)

Expected after implementation (dry-run verified; live times vary):

| Path | Dominant stages |
|------|-----------------|
| Quality 8K character | i2d poll, rig, animate (3 idles), download |
| Game-ready vehicle | i2d poll, download, QC |
| Unity import (happy) | Package inject + Editor compile + C# import (no LLM) |

**Live metrics:** after a successful `unity_import`, query `pipeline_timing_stats` (see [DB-TIMING.md](DB-TIMING.md)) or `pipelines.metadata.timing_stats`. Per-stage `duration_ms` is on `pipeline_stages` and in log viewer.

Orchestration is **already optimized** for v0.2; remaining wall time is mostly **Meshy/API poll** and **manual concept gates**. See DB-TIMING.md for DBA review and further optimization levers.

## Out of scope (v1)

Worldbuilding, Blender ARP, WheelCollider sim, Meshy TCP bridge, parallel Unity Editors, Python UnityMcpClient, forcing remesh on every Quality job.

## Test plan

✅ **Complete:** pytest covers payload shapes, remesh skip, asset_kind branching, Unity lock, s11 happy path (dry-run), MCP bridge selection, timing rollup (`tests/test_enhancements.py`, `test_pipeline_timing.py`, `test_workflow.py`).

🔄 **In queue:** documented live E2E checklist (Unity Editor open, real Meshy job, timing stats row populated) — run manually before tagging a release.
