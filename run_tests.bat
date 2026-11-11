@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [AAA] Virtual env not found: .venv\Scripts\python.exe
    echo.
    echo Setup:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip.exe install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

echo [AAA] Ruff check...
"%PY%" -m ruff check asset_assembly_automator tests
if errorlevel 1 goto :failed

echo [AAA] Ruff format check...
"%PY%" -m ruff format --check asset_assembly_automator tests
if errorlevel 1 goto :failed

echo [AAA] Pytest...
"%PY%" -m pytest -q
if errorlevel 1 goto :failed

echo.
echo [AAA] All checks passed.
exit /b 0

:failed
echo.
echo [AAA] Tests failed with exit code %ERRORLEVEL%
pause
exit /b %ERRORLEVEL%
