# Contributing to Asset Assembly Automator

Thanks for your interest in contributing! This document covers the setup,
conventions, and guardrails for working in this repository.

## Prerequisites

- **Windows + PowerShell** (the launch scripts and paths are Windows-first).
- **Python 3.11+**.
- A local virtual environment at `.venv/`.

## Development setup

```powershell
# From the repo root
python -m venv .venv
.\.venv\Scripts\pip.exe install -e ".[dev]"
.\.venv\Scripts\python.exe -m asset_assembly_automator.cli init
```

Copy the example config/secrets templates and fill in your own keys — **never
commit real keys**:

```powershell
Copy-Item secrets.env.example "$env:USERPROFILE\.asset_assembly_automator\secrets.env"
Copy-Item mcp.json.example .mcp.json
```

Launch the apps:

```powershell
.\launch.bat            # Command Center (full pipeline)
.\launch-workflow.bat   # Meshy Workflow (concept -> Meshy -> Unity MCP)
```

## Secrets & configuration

- Store keys in `%USERPROFILE%\.asset_assembly_automator\secrets.env` (see
  [`secrets.env.example`](secrets.env.example)) or the OS keyring.
- **Meshy** — `MESHY_API_KEY`; also read by the Meshy MCP server via `.mcp.json`
  (see [`mcp.json.example`](mcp.json.example)).
- **Magnific** — `MAGNIFIC_API_KEY` (+ webhook signing secret).
- **Higgsfield** — hosted MCP OAuth on first GUI run (tokens stored under
  `%LOCALAPPDATA%\AssetAssemblyAutomator\mcp\higgsfield_oauth.json`, outside the
  repo), or set `HF_MCP_ACCESS_TOKEN`. REST fallback uses `HF_CREDENTIALS=KEY:SECRET`.
- Never log full API keys, OAuth tokens, or `Authorization` headers.
- The legacy repo-root `meshy-api.key` / `magnific-api.key` fallbacks are
  `.gitignore`d — do not commit them and migrate to secrets when possible.

## Coding standards

- **Ruff** for linting and formatting (line length 100, target Python 3.11):

  ```powershell
  .\.venv\Scripts\python.exe -m ruff check asset_assembly_automator tests
  .\.venv\Scripts\python.exe -m ruff format asset_assembly_automator tests
  ```

- **Pre-commit** hooks run Ruff automatically:

  ```powershell
  .\.venv\Scripts\pip.exe install pre-commit
  pre-commit install
  ```

- Chain shell commands with `;`, not `&&` / `||`.

## Testing

Run the test suite before opening a PR:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use fake provider clients (`FakeMeshyClient`, `FakeHiggsfieldClient`,
etc.) and isolated temp databases — they never spend API credits. Please keep
new tests offline and credit-free.

## Architecture invariants

Please read [`AGENTS.md`](AGENTS.md) before making structural changes. Key rules:

1. **Stages are the unit of work** — each stage module exposes
   `async def run(pipeline_id, *, dry_run, verbose, **kwargs) -> StageResult`
   and goes through `run_stage()` for logging and stage records.
2. **SQLite is the source of truth** for pipeline state, job IDs, prompts,
   assets, and logs — never bypass the `Database` layer for mutations.
3. **Dry-run uses fakes** — no live API calls in tests.
4. Store Meshy/Higgsfield task IDs in `external_jobs` immediately after creation.
5. Do not wire Phase 2 stages (world pipeline, Unity import, Blender/ARP) into
   the runner without explicit scope.

## Pull requests

1. Create a feature branch off `main`.
2. Ensure `ruff check` and `pytest` pass.
3. Confirm no secrets are staged: `git status` should never show `*.key`,
   `secrets.env`, or `.mcp.json`.
4. Write a clear PR description of what changed and why.

## Reporting issues

Open a GitHub issue with reproduction steps, expected vs. actual behavior, and
relevant log excerpts (redact any keys/tokens). Logs live under
`{project.output_root}\Characters\{asset}\logs\{pipeline_id}\pipeline.jsonl` and
in the SQLite `log_entries` table — see [`AGENTS.md`](AGENTS.md) for details.
