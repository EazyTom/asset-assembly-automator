$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$python = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw ".venv not found. Run: .venv\Scripts\pip.exe install -e `".[dev]`""
}

& $python -m PyInstaller packaging/aaa.spec --noconfirm
Write-Host "Build output: dist/AssetAssemblyAutomator/"
