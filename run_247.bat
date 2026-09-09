@echo off
title Lighter Trading Bot - 24/7 Watchdog Supervisor
color 0A

echo =======================================================
echo   LIGHTER 24/7 SUPERVISOR (single restart tree)
echo   Canonical: bot.pid + sniper_app.log
echo   Do not also run watchdog.bat / watchdog_loop.ps1
echo =======================================================
echo.

cd /d "%~dp0"
set PYTHONPATH=%~dp0
set PYTHONUNBUFFERED=1
rem Set MM_ENABLED=1 to enable the market-maker child process.

if exist "C:\Program Files\Python312\python.exe" (
  "C:\Program Files\Python312\python.exe" -u "%~dp0watchdog_supervisor.py"
) else (
  python -u "%~dp0watchdog_supervisor.py"
)
