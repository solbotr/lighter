# Legacy loop. Prefer run_247.bat -> watchdog_supervisor.py (single restart tree).
# Do not run this alongside watchdog_supervisor.py.
# Canonical bot log: sniper_app.log (not sniper.log)
$ErrorActionPreference = "SilentlyContinue"
$log = "C:\LighterBot\watchdog.log"
while ($true) {
    $running = Get-Process python -ErrorAction SilentlyContinue
    if (-not $running) {
        Add-Content $log ("{0} python down - restarting" -f (Get-Date -Format o))
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c C:\LighterBot\run_live.bat" -WindowStyle Hidden
    }
    $sniper = Get-Item "C:\LighterBot\sniper_app.log" -ErrorAction SilentlyContinue
    if ($sniper -and $sniper.Length -gt 50MB) {
        Move-Item "C:\LighterBot\sniper_app.log" "C:\LighterBot\sniper_app.log.bak" -Force
        Add-Content $log ("{0} rotated sniper_app.log" -f (Get-Date -Format o))
    }
    Start-Sleep -Seconds 30
}
