# Unity import repair (Unity MCP — default AnkleBreaker)

Validation failed for `{asset_kind}` slug `{slug}`.

## Facts

- Unity project: `{unity_project_path}`
- Asset directory: `{asset_dir}`
- MCP bridge (configured): **`{mcp_server}`** / **{cursor_server_id}**
- Run C# via **`{execute_code_tool}`**; console via **`{console_tool}`**; preflight via **`{ping_tool}`**
- Do **not** re-download Meshy assets
- Do **not** use quick-import shortcuts for characters
- Fix only what the validator reported, then re-run validation via C# (do not skip ImportFromSlug)

## Validator JSON

```json
{validation_json}
```

## Repair steps

1. **`{ping_tool}`** — confirm Editor reachable (AnkleBreaker: `unity_editor_ping`)
2. Inspect console via **`{console_tool}`**
3. Fix missing textures, animator clips, or components using **`{execute_code_tool}`** / menu items
4. Call `CharacterManifestImportUtility.ImportFromSlug("{slug}")` or kind-specific import if needed
5. Summarize fixes; do not claim success unless validation would pass

> **Bridge fallbacks:** AAA defaults to AnkleBreaker (`unity` / user-unity). Coplay (`user-unityMCP`, `execute_code`) and Official (`user-unity-mcp`, `Unity_*` tools) are supported — see appended bridge table in Facts.
