@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo [AAA] Virtual env not found: .venv\Scripts\python.exe
    echo.
    echo Setup:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip.exe install -e .
    echo.
    pause
    exit /b 1
)

"%PY%" -m asset_assembly_automator.gui.main
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
    echo.
    echo [AAA] GUI exited with code %ERR%
    pause
    exit /b %ERR%
)

endlocal
