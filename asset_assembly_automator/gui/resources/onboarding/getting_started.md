# Getting Started — Asset Assembly Automator

Welcome! Configure services before running pipelines.

## Required

### 1. Meshy API key

[Get key](https://www.meshy.ai/settings/api) — required for image-to-3D, rig, animate, and FBX export.

### 2. Unity 6 + Unity MCP (for `unity_import`)

Required when running **Import to Unity** (`s11`), **Remove from Unity**, or **Tools → Diagnostics** Unity ping.

| Requirement | Details |
|-------------|---------|
| **Unity 6 Editor** | Install via Unity Hub; open the **target project** while AAA import/repair runs |
| **Unity project path** | Set in Workflow app or Command Center project settings |
| **Unity MCP bridge** | Default **AnkleBreaker** (`unity` / **user-unity**). Coplay + Official supported — **Settings → Unity MCP bridge** |
| **Agent CLI** | `cursor-agent` or `claude` on PATH for repair/Diagnostics (Settings → Agent for Unity repair) |

**Happy-path import** is predetermined C# (`com.assetassembly.import` package). **Unity MCP is still required** for validation-failure repair, cleanup, and Diagnostics.

#### Unity MCP — default + fallbacks

| Priority | Bridge | Cursor server id | Config |
|----------|--------|------------------|--------|
| **1 — Default** | **AnkleBreaker** | `unity` / **user-unity** | [`mcp.json.example`](../../../../mcp.json.example) `unity` block |
| **2 — Fallback** | **Coplay Unity MCP** | **user-unityMCP** | [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) |
| **3 — Fallback** | **Official Unity MCP** | **user-unity-mcp** | [Unity MCP overview](https://docs.unity3d.com/Packages/com.unity.ai.assistant@2.0/manual/unity-mcp-overview.html) |

Copy `mcp.json.example` → `.mcp.json` at repo root (gitignored). Enable **one** Unity bridge at a time.

## Optional — concept art (pick one or more)

You need an approved reference image before Meshy, but **not** Higgsfield specifically:

- **Midjourney** — manual generate + watch-folder import or drag-drop (no API). Preview native images first.
- **Magnific** — REST upscaler **after you approve** a concept (Workflow auto stage / Command Center `magnific_uprez`). Optional Mystic generate for a native preview (**Use Magnific**).
- **Higgsfield** — optional MCP/REST concept generate (Workflow **Use Higgs**; Command Center **Refine**)

## Optional — Phase 2

- **Blender MCP + Auto-Rig Pro** — fallback rig (not wired in v1)

## Docs

- [Workflow guide](../../midjourney_meshy_unity_mcp_character_workflow.md)
- [Meshy Rigging API](https://docs.meshy.ai/en/api/rigging-and-animation)
- [ASSET-ASSEMBLY-AUTOMATOR.md](../../../../ASSET-ASSEMBLY-AUTOMATOR.md)
- [ENHANCEMENTS.md](../../../../docs/ENHANCEMENTS.md)
