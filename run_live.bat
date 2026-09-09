@echo off
REM One-shot live launch (no restart loop). Prefer run_247.bat -> watchdog_supervisor.py
REM for 24/7. Canonical bot log: sniper_app.log
cd /d "%~dp0"
if exist "C:\LighterBot\lighter_news_sniper.py" (
  cd /d C:\LighterBot
)
set PYTHONPATH=%CD%
set PYTHONUNBUFFERED=1
if exist "C:\Program Files\Python312\python.exe" (
  "C:\Program Files\Python312\python.exe" -u "%CD%\lighter_news_sniper.py" --live --margin-pct 85 >> "%CD%\sniper_app.log" 2>&1
) else (
  python -u "%CD%\lighter_news_sniper.py" --live --margin-pct 85 >> "%CD%\sniper_app.log" 2>&1
)
