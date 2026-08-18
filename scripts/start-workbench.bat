@echo off
REM ============================================================================
REM start-workbench.bat - Windows service launcher for the Hermes personal
REM workbench (U3).
REM
REM Starts the workbench dashboard API (which also runs the scheduler center:
REM crash recovery + worker pool + cron scheduler), redirects logs to
REM %HERMES_DATA_DIR%\logs\workbench.log (or .\logs if unset) and performs a
REM one-time health poll. Register with Task Scheduler for auto-start at logon:
REM
REM   schtasks /create /tn "HermesWorkbench" /tr "cmd /c D:\Hermes\hermes\scripts\start-workbench.bat" /sc onlogon /rl limited
REM
REM For "run whether user is logged on or not" /rl highest is required (needs
REM admin and stored credentials).
REM ============================================================================
setlocal enabledelayedexpansion

set "HERMES_ROOT=%~dp0..\"
set "VENV_PY=%HERMES_ROOT%.venv\Scripts\python.exe"
set "HERMES_BIN=%VENV_PY%"

if "%HERMES_DATA_DIR%"=="" set "HERMES_DATA_DIR=%HERMES_ROOT%data"
set "LOGS_DIR=%HERMES_DATA_DIR%\logs"
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"

set "PORT=8000"
if not "%HERMES_WORKBENCH_PORT%"=="" set "PORT=%HERMES_WORKBENCH_PORT%"

echo [start-workbench] hermes root : %HERMES_ROOT%
echo [start-workbench] data dir     : %HERMES_DATA_DIR%
echo [start-workbench] port         : %PORT%
echo [start-workbench] log file     : %LOGS_DIR%\workbench.log

if not exist "%VENV_PY%" (
    echo [start-workbench] ERROR: venv not found at %VENV_PY%
    echo [start-workbench] Run: python -m venv .venv  ^&^&  pip install -e .
    exit /b 1
)

set "HERMES_DATA_DIR=%HERMES_DATA_DIR%"
echo [start-workbench] starting hermes workbench serve...
"%HERMES_BIN%" -m hermes.main workbench serve --host 127.0.0.1 --port %PORT% >> "%LOGS_DIR%\workbench.log" 2>&1

REM If the server exits, log it so watchdog / logs can diagnose.
echo [start-workbench] workbench server exited with code %ERRORLEVEL% >> "%LOGS_DIR%\workbench.log"
exit /b %ERRORLEVEL%
