# Unity import — {character_slug}

You are a Cursor agent with Unity MCP. **AAA default:** AnkleBreaker server **`unity`** (Cursor **`user-unity`**) — use **`unity_*` tools**. Unity 6 Editor must be open on `{unity_project_path}` with the bridge connected. Use MCP tools only — no Python in this repo.

> **Default bridge:** AnkleBreaker [`unity-mcp-server`](https://github.com/naniknataraj/unity-mcp-server) — `mcp.json.example` `unity` block. **Supported fallbacks:** Coplay **`user-unityMCP`** (`execute_code`, …) and Official **`user-unity-mcp`** (`Unity_*` tools). See appended Facts for configured bridge + tool mapping. Only one Unity MCP server should be active.

## Goal

Import the rigged Meshy humanoid `{character_slug}`, wire an Animator Controller with **Idle3 / Idle4 / Idle12 / Walk / Run**, apply its material/texture, place it on the terrain, and make it **cycle idle animations with occasional oval walking** in Play mode.

All FBXs, textures, and `unity_import_manifest.json` are already staged under `{character_dir}` by the AAA pipeline (see Facts). **Do not** re-download, re-extract, or copy files unless the manifest or staged Source folder is missing.

## Architecture note (v0.2)

Normal **`s11_unity_import`** runs a **deterministic C# watcher** (`com.assetassembly.import` UPM package) and only invokes an agent on validation failure (`unity_import_repair.md`). Use this workflow when driving a **manual agent import** from the Workflow app prompt editor or when C# import is unavailable.

## Hard constraints

- **Do NOT** use quick-import shortcuts that skip clips, controller, or patrol.
- **Do NOT** run inline reimport loops that call `ModelImporter.SaveAndReimport()` on every FBX — blocked by MCP user-interaction guards.
- **Do NOT** `glob`, `grep`, read `.fbx.meta`, or explore other characters. Everything you need is in Facts + manifest.
- **Do NOT** hand-edit `.meta` files. Import settings are applied by `CharacterManifestImportUtility` in the Unity project.
- **Do NOT** improvise alternate import approaches if a step fails — retry the same step once, then report verbatim errors.

## Prerequisites (Unity project — installed automatically)

AAA **s11** injects `com.assetassembly.import` before import:

| Asset | Purpose |
|-------|---------|
| `CharacterManifestImportUtility` (UPM) | Manifest-driven import (humanoid rig, clips, controller, material, prefab, scene placement, `CharacterOvalPatrol`) |
| `CharacterOvalPatrol` (UPM) | Cycles Idle3/Idle4/Idle12 while standing; occasionally walks an oval |

Import is triggered by calling `CharacterManifestImportUtility.ImportFromSlug("{character_slug}")` via **`unity_execute_code`**, or menu **Tools → Characters → Import character from manifest...** via **`unity_execute_menu_item`**.

---

## MCP tool chain (AnkleBreaker — run in order)

### Phase 0 — Preflight

| Step | Tool | Args / notes | Success signal |
|------|------|--------------|----------------|
| 0a | `unity_editor_ping` | `{}` | Editor reachable |
| 0b | `unity_editor_state` | poll until not compiling | Not compiling (max 90s) |
| 0c | `unity_console_log` | baseline | Note existing errors before import |
| 0d | `unity_asset_list` | search `CharacterManifestImportUtility` under project | UPM import utilities present |

If 0d fails, report: *"AAA import package missing — re-run Unity import from the workflow app (s11 injects UPM automatically)."*

### Phase 1 — Import (primary path)

**Preferred:** `unity_execute_code` calling `ImportFromSlug`.

| Step | Tool | Code / notes | Success signal |
|------|------|--------------|----------------|
| 1a | `unity_execute_code` | see **Script ImportFromSlug** below | No compile errors; import logs present |
| 1b | `unity_console_log` | `{}` | Contains `[Import] Prefab saved: Assets/Characters/{character_slug}/Prefabs/PF_{character_slug}.prefab` and `[Import] Placed PF_{character_slug}` |

**Optional manual path:** `unity_execute_menu_item` → **Tools/Characters/Import character from manifest...** and enter `{character_slug}`.

```csharp
#if UNITY_EDITOR
using UnityEditor;
CharacterManifestImportUtility.ImportFromSlug("{character_slug}");
UnityEngine.Debug.Log("[Import] ImportFromSlug invoked for {character_slug}");
#endif
```

**Import failed** if console has `[Import] Manifest not found`, `[Import] Rig FBX missing`, `[Import] Mesh FBX failed`, or no prefab-saved line after 1a.

### Phase 2 — Cleanup duplicates

Prior quick-import attempts may leave stray objects.

| Step | Tool | Notes |
|------|------|-------|
| 2a | `unity_gameobject_delete` | Delete scene object named `{character_slug}` or duplicate `PF_{character_slug}` if not the manifest instance |
| 2b | `unity_asset_delete` | Delete `Assets/ExternalModels/{character_slug}` if present |

### Phase 3 — Verify import

| Step | Tool | Expected |
|------|------|----------|
| 3a | `unity_asset_list` | Under `Assets/Characters/{character_slug}` — prefab, controller, walk/run anims, material |
| 3b | `unity_gameobject_info` + `unity_component_get_properties` | `PF_{character_slug}` has `Animator` + `CharacterOvalPatrol` |
| 3c | `unity_execute_code` | see **Script VerifyClips** below — Walk len > 0.5, Run len > 0.3 |

```csharp
#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
var root = "Assets/Characters/{character_slug}/Animations";
var walk = AssetDatabase.LoadAssetAtPath<AnimationClip>(root + "/{character_slug}_Walk.anim");
var run = AssetDatabase.LoadAssetAtPath<AnimationClip>(root + "/{character_slug}_Run.anim");
Debug.Log("Walk len=" + (walk != null ? walk.length.ToString("F2") : "MISSING"));
Debug.Log("Run len=" + (run != null ? run.length.ToString("F2") : "MISSING"));
if (walk == null || walk.length < 0.02f)
    Debug.LogError("Walk clip missing or zero-length — avatar copy failed");
#endif
```

### Phase 4 — Save and Play

| Step | Tool | Success signal |
|------|------|----------------|
| 4a | `unity_scene_save` | Scene saved |
| 4b | `unity_play_mode` | Enter play mode — character idle-cycles and occasionally walks oval |

> **Play-mode note:** MCP may be unavailable while playing. Stop Play before further MCP steps.

---

## MCP tools — use vs avoid

### Use these (`unity_*` only)

| Tool | Role |
|------|------|
| `unity_editor_ping` / `unity_editor_state` | Reachability + wait for compile |
| `unity_execute_code` | **Primary** — call `ImportFromSlug`, verify clip lengths |
| `unity_execute_menu_item` | Optional manifest menu import |
| `unity_console_log` | Confirm import success / read warnings |
| `unity_asset_list` / `unity_search_assets` | Verify staged output assets |
| `unity_gameobject_delete` / `unity_gameobject_info` | Remove duplicates, verify prefab |
| `unity_component_get_properties` | Confirm Animator + patrol script |
| `unity_asset_delete` | Delete ExternalModels leftovers |
| `unity_scene_save` | Save scene |
| `unity_play_mode` | Enter/exit play for visual check |

### Avoid (unless using Official/Coplay fallback mapping)

| Approach | Why |
|----------|-----|
| Wrong MCP server for configured bridge | Tool names differ — follow Facts bridge table |
| Inline per-FBX `SaveAndReimport` loops | User-interaction guard failures |
| MCP calls during Play mode | Connection drops — stop Play first |

---

## Done when

- `Character_output.fbx` imported as **Humanoid** with valid avatar.
- Walk clip length **> 0.5s**, Run clip **> 0.3s**.
- `MAT_{character_slug}_Body.mat` assigned — character is not magenta/untextured.
- `{character_slug}_Controller` has **Idle3 / Idle4 / Idle12 / Walk / Run** with `Gait` + `IdleIndex`; default **Idle3**.
- `PF_{character_slug}` in scene on terrain with `CharacterOvalPatrol`.
- Play mode shows idle cycling with occasional oval walking.

Report: console lines from Phase 1b, clip lengths from Phase 3c, prefab/controller/material paths, and any warnings verbatim.
