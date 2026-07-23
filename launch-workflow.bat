@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [AAA Workflow] Virtual env not found: .venv\Scripts\python.exe
    echo.
    echo Setup:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip.exe install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

"%PY%" -m asset_assembly_automator.gui.workflow_main
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo.
    echo [AAA Workflow] GUI exited with code %ERR%
    pause
    exit /b %ERR%
)

endlocal
