@echo off
setlocal
cd /d "%~dp0"
set "TAPO_PYTHON=%LOCALAPPDATA%\TapoDesk\python-runtime\Scripts\pythonw.exe"
set "TAPO_RUNTIME="
if exist ".windows-runtime" (
    set /p TAPO_RUNTIME=<".windows-runtime"
)
if defined TAPO_RUNTIME set "TAPO_PYTHON=%TAPO_RUNTIME%\Scripts\pythonw.exe"
if not exist "%TAPO_PYTHON%" set "TAPO_PYTHON=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%TAPO_PYTHON%" (
    echo Please run setup.ps1 first to install Tapo Desk.
    pause
    exit /b 1
)
start "Tapo Desk" "%TAPO_PYTHON%" "run.py" %*
