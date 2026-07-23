param(
    [string]$InputJson = "{}"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $repoRoot

$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Skip ruff hook: .venv not found"
    exit 0
}

$filePath = $null
try {
    $payload = $InputJson | ConvertFrom-Json
    if ($payload.file_path) { $filePath = $payload.file_path }
    elseif ($payload.path) { $filePath = $payload.path }
} catch {
    # ignore parse errors
}

if ($filePath -and $filePath -notmatch '\.py$') {
    exit 0
}

if ($filePath) {
    & $python -m ruff format $filePath
    & $python -m ruff check --fix $filePath
} else {
    & $python -m ruff format asset_assembly_automator tests
    & $python -m ruff check --fix asset_assembly_automator tests
}

if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
exit 0
