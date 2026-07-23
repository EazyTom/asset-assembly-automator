# Asset Assembly Automator (AAA)

**Version 0.1.0** — Python + PyQt6 orchestrator for the Midjourney/Higgsfield → Meshy → FBX.zip character pipeline.

Automates concept art generation (Higgsfield), manual-assisted Midjourney compare, Meshy image-to-3D, remesh-to-budget, rig, custom animations, download, QC, and Unity-ready zip export. **Unity MCP import** is implemented for the Meshy Workflow app (`s11`); worldbuilding stages remain Phase 2 stubs.

### Documentation map

| Doc | Role |
|-----|------|
| [README.md](README.md) | Developer overview — architecture diagrams, both GUIs, data model |
| [AAA-WORKFLOW.md](AAA-WORKFLOW.md) | Meshy Workflow app + Unity MCP import chain |
| **ASSET-ASSEMBLY-AUTOMATOR.md** (this file) | Product spec — stages, CLI, config, providers |
| [AGENTS.md](AGENTS.md) | AI agent guardrails |
| [config/workflows/unity_import.md](config/workflows/unity_import.md) | Unity MCP import prompt (agent source of truth) |

---

## Quick start

**Command Center** (full pipeline):

```powershell
cd D:\Repos\asset-assembly-automator
python -m venv .venv
.\.venv\Scripts\pip.exe install -e ".[dev]"
.\.venv\Scripts\python.exe -m asset_assembly_automator.cli init
.\.venv\Scripts\python.exe -m asset_assembly_automator.cli create-project MyGame "D:\Output"
.\.venv\Scripts\python.exe -m asset_assembly_automator.cli create-pipeline 1 HeroCourier --poly-budget hero
.\.venv\Scripts\python.exe -m asset_assembly_automator.cli run --pipeline-id 1 --dry-run
.\launch.bat
```

**Meshy Workflow** (T-pose drop → Meshy → Unity import): `.\launch-workflow.bat` or `aaa-workflow`

Set Meshy API key via GUI **Settings** or `%USERPROFILE%\.asset_assembly_automator\secrets.env`:

```
MESHY_API_KEY=your_key_here
```

---

## Architecture

```mermaid
flowchart TD
    subgraph concept [Concept]
        PB[prompt_build]
        CG[concept_generate]
        CR[concept_review]
        IP[image_prep]
        TA[turnaround optional]
    end
    subgraph meshy [Meshy]
        I2D[meshy_i2d]
        RM[meshy_remesh]
        RG[meshy_rig]
        AN[meshy_animate]
        DL[meshy_download]
        QC[meshy_qc]
        ZIP[package_export]
    end
    subgraph phase2 [Phase 2 optional]
        UI[unity_import s11]
        CUR[Cursor CLI agent]
        MCP[user-unity-mcp]
    end
    PB --> CG --> CR --> IP
    IP --> TA --> I2D
    IP --> I2D
    I2D --> RM --> RG --> AN --> DL --> QC --> ZIP
    ZIP -.->|Workflow app only| UI
    UI --> CUR --> MCP
```

### Components

| Layer | Path | Role |
|-------|------|------|
| Core | `core/` | Config, logging, secrets, state machine, SQLite |
| Clients | `clients/` | Meshy, Higgsfield, Cursor CLI, animation catalog, image prep |
| Stages | `stages/s01_*` … `s11_*` | Standalone async stage scripts |
| Orchestrator | `orchestrator/` | Runner, resume, watchdog watchers |
| Workflow | `workflow/` | Bootstrap, Unity MCP prompt compose/run, templates |
| GUI | `gui/` | Command Center (`main.py`) + Meshy Workflow (`workflow_main.py`) |
| CLI | `cli.py` | `aaa` commands |

### State & resume

- SQLite DB: `%LOCALAPPDATA%\AssetAssemblyAutomator\aaa.db`
- Pipeline `current_stage` + `external_jobs.task_id` enable resume after crash
- `orchestrator/resume.py` finds active pipelines mid-Meshy and checks job expiry

---

## Pipeline stages

| Stage | CLI module | Manual gate? | Notes |
|-------|------------|--------------|-------|
| `prompt_build` | `s01_prompt_build` | No | Renders MJ/HF/Meshy prompts from YAML templates |
| `concept_generate` | `s02_concept_generate` | No | Higgsfield MCP adapter (fake in dry-run) |
| `concept_review` | `s03_concept_review` | **Yes** | Approve MJ or HF concept → T-pose PNG |
| `image_prep` | `s04_image_prep` | No | T-pose checklist, optional crop |
| `turnaround` | `s04b_turnaround` | No | Opt-in multi-view for `multi-image-to-3d` |
| `meshy_i2d` | `s05_meshy_image_to_3d` | No | t-pose, quad, PBR, FBX+GLB |
| `meshy_remesh` | `s06_meshy_remesh` | No | Remesh to budget (default max 300k tris; skipped if i2d already within target) |
| `meshy_rig` | `s07_meshy_rig` | No | Includes free walk + run FBXs |
| `meshy_animate` | `s08_meshy_animate` | No | Custom clips from catalog (3 credits each) |
| `meshy_download` | `s09_meshy_download` | No | Downloads rig + clips + textures |
| `meshy_qc` | `s09b_qc_validate` | No | Polycount / file presence gate |
| `package_export` | `s10_package_export` | No | FBX.zip + `pipeline_manifest.json` |
| `unity_import` | `s11_unity_import` | No | Stage FBXs into Unity project; Cursor CLI → `user-unity-mcp` (**Workflow app only**) |

Run a single stage:

```powershell
.venv\Scripts\python.exe -m asset_assembly_automator.stages.s05_meshy_image_to_3d --pipeline-id 1 --dry-run
```

---

## CLI reference

| Command | Description |
|---------|-------------|
| `aaa init` | Create app data dir + SQLite schema |
| `aaa create-project NAME OUTPUT_ROOT [--unity PATH]` | New project |
| `aaa create-pipeline PROJECT_ID ASSET_NAME [--poly-budget hero\|npc\|crowd] [--multi-view]` | New character pipeline |
| `aaa run --pipeline-id N [--stage STAGE] [--dry-run] [--verbose] [--manual]` | Run pipeline or one stage |
| `aaa watch [--pipeline-id N] [--output-dir PATH] [--duration SEC]` | Watch MJ import folder |

Entry points (after install): `aaa`, `aaa-gui`, `aaa-workflow`, `asset-assembly-automator`, `asset-assembly-automator-gui`.

---

## GUI

Two windows share `PipelineController`, SQLite, and stage modules:

| App | Launch | Scope |
|-----|--------|-------|
| **Command Center** | `launch.bat` / `aaa-gui` | Full pipeline: prompts, concept, Meshy, export |
| **Meshy Workflow** | `launch-workflow.bat` / `aaa-workflow` | T-pose drop → Meshy → Unity MCP import |

### Command Center (`gui/main.py`)

- **Dashboard**: pipeline cards, run controls, stepper
- **Focused wizard**: step list via toolbar **Focused Mode**
- **Prompt builder**, **concept compare**, **animation picker**, **log tail**
- **Phase 2 stub** view for world / Unity placeholders
- **Settings**: Meshy key, MJ watch folder, theme, onboarding toggles
- **Getting Started** / **What's New** markdown dialogs

### Meshy Workflow (`gui/workflow_main.py`)

- Drag-and-drop T-pose **drop zone** → bootstrap pipeline
- **MeshyWorkflowStepper** (Meshy stages + Unity import)
- Editable Unity import prompt (from `config/workflows/unity_import.md`)
- **Import to Unity** / **Remove from Unity** via Cursor CLI

Async: qasync event loop + `PipelineController` schedules `asyncio.Task` per pipeline run.

---

## Configuration

Layered config (`core/config.py`):

1. `config/default.yaml` (repo)
2. `%USERPROFILE%\.asset_assembly_automator\config.yaml` (user override)
3. Environment variables with `AAA_` prefix

Key Meshy settings:

```yaml
meshy:
  hd_texture: true          # 4K base color (meshy-6 / latest)
  model_type: standard
  i2d_target_polycount:
    hero: 300000
    npc: 300000
    crowd: 300000
  remesh_target_tris:
    hero: 300000
    npc: 300000
    crowd: 300000
  hard_rig_face_limit: 300000
  animation_fps: 30
```

Cursor CLI (Unity import):

```yaml
cursor_cli:
  enabled: true
  command: cursor-agent
  timeout_seconds: 900
```

Prompt templates: `config/prompt_templates/*.yaml`  
Unity workflows: `config/workflows/unity_import.md`, `unity_import_cleanup.md`

---

## Output layout

```
{output_root}/Characters/{slug}/
  Concept/
  TPose/
  Source/          # Character_output.fbx, Animation_Walking/Running_withSkin.fbx
  Animations/      # walk, run, custom clips
  Textures/
  CHR_{name}_MeshyExport.zip    # or legacy CHR_{name}_UnityImport_v01.zip
  pipeline_manifest.json
```

Meshy does **not** export one merged animated FBX. The zip contains separate rig + clip FBXs for Unity Humanoid setup. Import automation runs via `s11` + Cursor agent + `user-unity-mcp` (see [AAA-WORKFLOW.md](AAA-WORKFLOW.md)).

---

## Animation defaults

Synced from `https://api.meshy.ai/web/public/animations/resources`:

- Walking (free with rig)
- Running (free with rig)
- Casual Walk (custom, resolved by catalog search)

Cache: `%LOCALAPPDATA%\AssetAssemblyAutomator\animation_catalog.json`

---

## Testing

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check asset_assembly_automator tests
```

Offline tests use `FakeMeshyClient` / `FakeHiggsfieldClient` / `FakeCursorCliClient` — no API spend.

---

## Packaging (Windows)

```powershell
.\packaging\build.ps1
```

Produces `dist/AssetAssemblyAutomator/` one-folder PyInstaller build.

---

## Phase 2

| Feature | Status |
|---------|--------|
| `unity_import` (`s11`) | **Implemented** — runnable from Meshy Workflow app via Cursor CLI + `user-unity-mcp`; not auto-run from Command Center |
| `world_concept`, `world_i2d`, `world_remesh`, `world_export` | Schema + GUI stub only |
| Blender + Auto-Rig Pro | `clients/blender_arp_client.py` fallback rig — not wired to runner |

World pipeline creation in Command Center shows an informational dialog — not runnable in v1.

---

## MCP / API matrix (summary)

See `midjourney_meshy_unity_mcp_character_workflow.md` for the full proven workflow.

| Provider | Capability |
|----------|------------|
| Higgsfield | `generate_image` via MCP adapter |
| Midjourney | Manual + watch folder import |
| Meshy | Full REST pipeline (i2d, remesh, rig, animate, download) |
| Unity | Cursor CLI agent → **`user-unity-mcp`** → `CharacterManifestImportUtility` (Workflow app trigger) |

Unity import details: [config/workflows/unity_import.md](config/workflows/unity_import.md).

---

## Agent guardrails

See [AGENTS.md](AGENTS.md) for contributor rules, threading invariants, and provider anti-assumptions.
