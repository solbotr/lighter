@echo off
REM Legacy thin check. Prefer run_247.bat -> watchdog_supervisor.py (single restart tree).
REM Do not run this alongside watchdog_supervisor.py.
REM Canonical bot log: sniper_app.log (not sniper.log)
cd /d C:\LighterBot
tasklist | findstr /I python.exe >nul
if errorlevel 1 (
  echo %DATE% %TIME% python down - restarting >> C:\LighterBot\watchdog.log
  start /B C:\LighterBot\run_live.bat
)
for %%F in (C:\LighterBot\sniper_app.log) do (
  if %%~zF GTR 52428800 (
    move /Y C:\LighterBot\sniper_app.log C:\LighterBot\sniper_app.log.bak >nul
    echo %DATE% %TIME% rotated sniper_app.log >> C:\LighterBot\watchdog.log
  )
)
