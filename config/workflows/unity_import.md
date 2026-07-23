# Unity import — {character_slug}

You are a Cursor agent with **Unity MCP** server **`user-unity-mcp`** (Unity AI MCP). Unity Editor must be open on `{unity_project_path}` with the MCP bridge connected. Use MCP tools only — no Python in this repo.

> **Server note:** `user-unityMCP` (MCP-for-Unity / coplaydev) is a different bridge and may show `Not connected`. Always use **`user-unity-mcp`** unless the user explicitly connected the other one.

## Goal

Import the rigged Meshy humanoid `{character_slug}`, wire an Animator Controller with **Idle3 / Idle4 / Idle12 / Walk / Run**, apply its material/texture, place it on the terrain, and make it **cycle idle animations with occasional oval walking** in Play mode.

All FBXs, textures, and `unity_import_manifest.json` are already staged under `{character_dir}` by the AAA pipeline (see Facts). **Do not** re-download, re-extract, or copy files unless the manifest or staged Source folder is missing.

## Hard constraints (follow exactly — deviations caused failed runs)

- **Do NOT** use `Unity_ImportExternalModel` for rigged characters. It imports only the rig FBX to `Assets/ExternalModels/`, skips walk/run clips, animator controller, and patrol.
- **Do NOT** run inline `Unity_RunCommand` scripts that call `ModelImporter.SaveAndReimport()` in a loop. MCP blocks these with `User interactions are not supported`.
- **Do NOT** `glob`, `grep`, read `.fbx.meta`, or explore other characters. Everything you need is in Facts + manifest.
- **Do NOT** hand-edit `.meta` files. Import settings are applied by `CharacterManifestImportUtility` in the Unity project.
- **Do NOT** improvise alternate import approaches if a step fails — retry the same step once, then report verbatim errors.

## Prerequisites (Unity project — installed automatically)

AAA **s11** copies these helper scripts from `unity_templates/` into the Unity project before the MCP agent runs:

| Asset | Purpose |
|-------|---------|
| `Assets/Editor/CharacterManifestImportUtility.cs` | Manifest-driven import (humanoid rig, clips, controller, material, prefab, scene placement, `CharacterOvalPatrol`) |
| `Assets/Scripts/CharacterOvalPatrol.cs` | Cycles Idle3/Idle4/Idle12 while standing; occasionally walks an oval, then returns to idling |

Import is triggered by calling `CharacterManifestImportUtility.ImportFromSlug("{character_slug}")` via `Unity_RunCommand` (primary for automation), or menu **Tools → Characters → Import character from manifest...**

---

## MCP tool chain (validated session — run in order)

### Phase 0 — Preflight

| Step | Tool | Args | Success signal |
|------|------|------|----------------|
| 0a | `Unity_ManageEditor` | `Action: "GetState"` | `IsCompiling: false`. If true, poll every 3s (max 90s). Reconnect if `Unity not detected` after domain reload. |
| 0b | `Unity_GetConsoleLogs` | `{}` | Baseline — note existing errors before import. |
| 0c | `Unity_ListResources` | `Under: "Assets/Editor"`, `Pattern: "CharacterManifestImportUtility.cs"` | File listed (AAA s11 should have copied it; if missing, stop and report — do not improvise import) |
| 0d | `Unity_ListResources` | `Under: "Assets/Scripts"`, `Pattern: "CharacterOvalPatrol.cs"` | File listed |

If 0c or 0d fail, report: *"AAA helper scripts missing — re-run Unity import from the workflow app (s11 copies scripts automatically)."*

### Phase 1 — Import (primary path)

**Preferred for automation:** `Unity_RunCommand` calling `ImportFromSlug` (no per-character menu required).

| Step | Tool | Args | Success signal |
|------|------|------|----------------|
| 1a | `Unity_RunCommand` | `Title: "Import {character_slug} from manifest"`, `Code:` see **Script ImportFromSlug** below | `isExecutionSuccessful: true` |

**Optional manual path:** menu **Tools/Characters/Import character from manifest...** and enter `{character_slug}`.

**Legacy fallback** (only if a per-slug menu was registered in an older project):

| Step | Tool | Args | Success signal |
|------|------|------|----------------|
| 1b | `Unity_ManageMenuItem` | `Action: "Execute"`, `MenuPath: "Tools/Characters/Import {character_slug} (manifest)"` | `executed: true` |

```csharp
using UnityEditor;

internal class CommandScript : IRunCommand
{
    public void Execute(ExecutionResult result)
    {
        CharacterManifestImportUtility.ImportFromSlug("{character_slug}");
        result.Log("ImportFromSlug invoked for {character_slug}");
    }
}
```

| 1c | `Unity_GetConsoleLogs` | `{}` | Contains `[Import] Prefab saved: Assets/Characters/{character_slug}/Prefabs/PF_{character_slug}.prefab` and `[Import] Placed PF_{character_slug}` |

**Import failed** if console has `[Import] Manifest not found`, `[Import] Rig FBX missing`, `[Import] Mesh FBX failed`, or no prefab-saved line after 1a.

### Phase 2 — Cleanup duplicates

Quick-import attempts or prior runs may leave stray objects. Remove them.

| Step | Tool | Args | Success signal |
|------|------|------|----------------|
| 2a | `Unity_ManageGameObject` | `action: "delete"`, `target: "{character_slug}"`, `search_method: "by_name"` | OK if object existed; ignore if not found |
| 2b | `Unity_ManageAsset` | `Action: "Delete"`, `Path: "Assets/ExternalModels/{character_slug}"` | OK if folder existed from `Unity_ImportExternalModel` |
| 2b-alt | `Unity_ManageAsset` | `Action: "Delete"`, `Path: "Assets/ExternalModels/{character_slug_with_underscores}"` | Use if slug contains hyphens (e.g. `magnifics_ramses`) |

### Phase 3 — Verify import

| Step | Tool | Args | Expected |
|------|------|------|----------|
| 3a | `Unity_ListResources` | `Under: "Assets/Characters/{character_slug}"`, `Pattern: "*"` | `PF_{character_slug}.prefab`, `{character_slug}_Controller.controller`, `magnifics-ramses_Walk.anim` (or `{character_slug}_Walk.anim`), `MAT_{character_slug}_Body.mat` |
| 3b | `Unity_ManageGameObject` | `action: "get_components"`, `target: "PF_{character_slug}"`, `search_method: "by_name"` | `Animator` (humanoid, `Gait` param, controller assigned) + `CharacterOvalPatrol` |
| 3c | `Unity_RunCommand` | `Title: "Verify clip lengths"`, `Code:` see **Script VerifyClips** below | Walk len > 0.5, Run len > 0.3 |

```csharp
using UnityEngine;
using UnityEditor;

internal class CommandScript : IRunCommand
{
    public void Execute(ExecutionResult result)
    {
        var root = "Assets/Characters/{character_slug}/Animations";
        var walk = AssetDatabase.LoadAssetAtPath<AnimationClip>(root + "/{character_slug}_Walk.anim");
        var run = AssetDatabase.LoadAssetAtPath<AnimationClip>(root + "/{character_slug}_Run.anim");
        result.Log("Walk len=" + (walk != null ? walk.length.ToString("F2") : "MISSING"));
        result.Log("Run len=" + (run != null ? run.length.ToString("F2") : "MISSING"));
        if (walk == null || walk.length < 0.02f)
            result.LogError("Walk clip missing or zero-length — avatar copy failed");
    }
}
```

### Phase 4 — Save and Play

| Step | Tool | Args | Success signal |
|------|------|------|----------------|
| 4a | `Unity_ManageScene` | `Action: "Save"` | Scene saved |
| 4b | `Unity_ManageEditor` | `Action: "Play"` | `Entered play mode` — character walks oval with Walk animation |

> **Play-mode note:** MCP may return `Unity not detected` while playing. That is expected. Stop Play in the Editor before running further MCP steps.

---

## What CharacterManifestImportUtility produces

| Output | Path |
|--------|------|
| Humanoid rig | `Assets/Characters/{character_slug}/Source/Character_output.fbx` |
| Extracted clips | `Assets/Characters/{character_slug}/Animations/{character_slug}_Idle3.anim`, `_Idle4.anim`, `_Idle12.anim`, `_Walk.anim`, `_Run.anim` |
| Animator controller | `Assets/Characters/{character_slug}/Controllers/{character_slug}_Controller.controller` |
| Material | `Assets/Characters/{character_slug}/Materials/MAT_{character_slug}_Body.mat` |
| Prefab | `Assets/Characters/{character_slug}/Prefabs/PF_{character_slug}.prefab` |
| Scene instance | `PF_{character_slug}` on terrain with `CharacterOvalPatrol` |

### Animator state machine

- Parameters: `Gait` (int) — `0=idle`, `1=Walk`, `2=Run`; `IdleIndex` (int) — `0=Idle3`, `1=Idle4`, `2=Idle12`
- Default state: **Idle3** (per manifest `animator.default_state`)
- `CharacterOvalPatrol` cycles `IdleIndex` while `Gait=0`, then occasionally sets `Gait=1` for oval walking before returning to idle
- Walk/run come free with Meshy rig; idle3/idle4/idle12 are generated in the Meshy animate stage (3 credits each)

---

## MCP tools — works vs avoid

### Use these

| Tool | Role |
|------|------|
| `Unity_ManageEditor` | `GetState` (wait for compile), `Play` |
| `Unity_ManageMenuItem` | Optional manual import menu |
| `Unity_RunCommand` | **Primary** — call `ImportFromSlug`, verify clip lengths |
| `Unity_GetConsoleLogs` | Confirm import success / read warnings |
| `Unity_ListResources` | Verify staged output assets |
| `Unity_ManageGameObject` | `get_components`, `delete` duplicates |
| `Unity_ManageAsset` | `Delete` ExternalModels leftovers |
| `Unity_ManageScene` | `GetHierarchy`, `Save` |

### Avoid these

| Tool | Why |
|------|-----|
| `Unity_ImportExternalModel` | Rig-only quick import; no animation state machine or patrol |
| `Unity_RunCommand` with full inline `ModelImporter` script | `SaveAndReimport` triggers `User interactions are not supported` |
| `user-unityMCP` tools (`execute_code`, `manage_asset` loops) | Different server; was not connected in live runs |
| MCP calls during Play mode | Connection drops — stop Play first |

---

## Decision tree

```
Phase 0: IsCompiling? → wait; helper scripts present?
  no  → report missing AAA helpers; stop
Phase 1: RunCommand ImportFromSlug
Phase 1c: Console shows Prefab saved + Placed?
  yes → Phase 2 cleanup
  no  → retry Phase 1 once → report error verbatim
Phase 3: Animator + CharacterOvalPatrol on PF_{slug}?
  yes → Phase 4 Play
  no  → report missing components; do not improvise
```

---

## Done when

- `Character_output.fbx` imported as **Humanoid** with valid avatar (zero-length idle warning is OK).
- Walk clip length **> 0.5s**, Run clip **> 0.3s** (avatar copied from rig).
- `MAT_{character_slug}_Body.mat` assigned — character is not magenta/untextured.
- `{character_slug}_Controller` has **Idle3 / Idle4 / Idle12 / Walk / Run** with `Gait` + `IdleIndex` transitions; default **Idle3**.
- `PF_{character_slug}` in scene on terrain with `CharacterOvalPatrol` (idle cycle + occasional oval walk).
- Play mode shows oval walking with Walk animation.

Report: console lines from Phase 1d, clip lengths from Phase 3c, prefab/controller/material paths, and any warnings verbatim.

---

## Automation recommendation

**Best chain for AAA pipeline (current architecture):**

1. **Python `s11_unity_import`** — copy helper scripts from `unity_templates/`, stage FBXs/textures + write `unity_import_manifest.json`.
2. **Cursor CLI agent** — run this workflow MD as the prompt (attached via `compose_import_prompt`).
3. **Agent executes Phases 0–4** using `user-unity-mcp` tools in order — no exploratory browsing.

**Optional Unity-project improvements (outside this repo):**

- Per-slug menu items are no longer required; generic menu + `ImportFromSlug` slug argument is enough.

**Not recommended:** replacing the manifest utility with inline `execute_code` / `Unity_RunCommand` reimport scripts — blocked by MCP user-interaction guard.
