#!/usr/bin/env python3
"""
VPS Remote Execution Utility (run_vps_cmd.py)
==============================================
Allows executing any command, status check, log tailing, or restart
directly on the AWS Windows VPS (18.153.70.154) in 1 line.

Usage:
    python scripts/run_vps_cmd.py "status"
    python scripts/run_vps_cmd.py "logs"
    python scripts/run_vps_cmd.py "restart"
    python scripts/run_vps_cmd.py "tasklist /FI \"IMAGENAME eq python.exe\""

Auth: VPS_PASS / VPS_SSH_KEY preferred; Desktop pass.txt is last resort (warned).
Host keys: ~/.ssh/known_hosts or VPS_HOST_KEY; AutoAdd only with warning.
"""

import base64
import os
import sys
from pathlib import Path

# Allow importing sibling deploy helpers from repo root
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import _vps_deploy as d

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Override deploy defaults from env when present
if os.getenv("VPS_HOST"):
    d.HOST = os.getenv("VPS_HOST")
if os.getenv("VPS_USER"):
    d.USER = os.getenv("VPS_USER")


def _ps_encoded(script: str) -> str:
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"powershell -NoProfile -EncodedCommand {enc}"


def execute_vps(cmd: str):
    try:
        ssh = d.connect()
    except Exception as e:
        print(f"Failed to connect to VPS {d.HOST}: {e}")
        return

    if cmd.lower() in ("status", "health"):
        real_cmd = _ps_encoded(
            "Write-Host '=== LIVE PROCESSES ==='; "
            "Get-Process python -ErrorAction SilentlyContinue | "
            "Select-Object Id, ProcessName, "
            "@{Name='Memory(MB)';Expression={[math]::Round($_.WS/1MB,2)}}, StartTime | "
            "Format-Table -AutoSize; "
            "Write-Host '=== SCHEDULED TASKS ==='; "
            "schtasks /query /tn 'LighterLiveBot' /fo LIST 2>$null | "
            "Select-String -Pattern 'TaskName|Status|Next Run Time'; "
            "schtasks /query /tn 'LighterRespawnGuard' /fo LIST 2>$null | "
            "Select-String -Pattern 'TaskName|Status|Next Run Time'; "
            "Write-Host '=== RECENT SNIPER LOGS ==='; "
            f"$p='{d.SNIPER_LOG}'; "
            f"if (-not (Test-Path $p)) {{ $p='{d.SNIPER_LOG_LEGACY}' }}; "
            "if (Test-Path $p) { Write-Output ('LOG=' + $p); Get-Content $p -Tail 15 } "
            "else { Write-Output 'LOG=missing' }"
        )
    elif cmd.lower() in ("logs", "log", "tail"):
        real_cmd = d.tail_log_cmd(35)
    elif cmd.lower() in ("restart", "reboot_bot"):
        restart_ps = (
            "Stop-ScheduledTask -TaskName LighterLiveBot -ErrorAction SilentlyContinue; "
            "$killed=@(); "
            f"$pidFile='{d.BOT_PID_FILE}'; "
            "if (Test-Path $pidFile) { "
            "  $bp=(Get-Content $pidFile -EA SilentlyContinue | Select-Object -First 1).Trim(); "
            "  if ($bp -match '^\\d+$') { taskkill /F /PID $bp 2>$null | Out-Null; $killed += [int]$bp } "
            "}; "
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -and ("
            "$_.CommandLine -like '*lighter_news_sniper.py*' -or "
            "$_.CommandLine -like '*watchdog_supervisor.py*') } | "
            "ForEach-Object { if ($killed -notcontains $_.ProcessId) { "
            "taskkill /F /PID $_.ProcessId 2>$null | Out-Null } }; "
            "Start-Sleep -Seconds 1; "
            "Start-ScheduledTask -TaskName LighterLiveBot -ErrorAction SilentlyContinue; "
            "Start-Sleep -Seconds 3; "
            "Get-Process python -EA SilentlyContinue | "
            "Select-Object Id, ProcessName, "
            "@{Name='Memory(MB)';Expression={[math]::Round($_.WS/1MB,2)}}, StartTime | "
            "Format-Table -AutoSize"
        )
        real_cmd = _ps_encoded(restart_ps)
    else:
        real_cmd = cmd

    try:
        stdin, stdout, stderr = ssh.exec_command(real_cmd)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if out:
            print(out)
        if err:
            print("STDERR:", err)
    except Exception as e:
        print(f"Execution error: {e}")
    finally:
        ssh.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python run_vps_cmd.py "status" | "logs" | "restart" | "<custom_cmd>"')
        sys.exit(1)
    command = " ".join(sys.argv[1:])
    execute_vps(command)
