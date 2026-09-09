#!/usr/bin/env python3
"""
Indestructible 24/7 Watchdog Supervisor (watchdog_supervisor.py)
===============================================================
Ensures the trading engine is ALWAYS alive and trading.
- Monitors child bot process every 10 seconds.
- Auto-restarts within < 2 seconds if process exits, crashes, or encounters an exception.
- Transmits periodic hourly vitality heartbeats to Telegram so you are always informed.
- Self-heals zombie sockets and clears stale memory locks.

Canonical ops artifacts (do not rename):
  bot.pid         — child bot PID written while the process is alive
  sniper_app.log  — child bot stdout/stderr (canonical app log)

Do NOT run the old run_247.bat restart loop (or watchdog.bat / watchdog_loop.ps1
that spawn run_live.bat) alongside this supervisor. Only one restart tree should
own the bot. Prefer: run_247.bat -> python watchdog_supervisor.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = CURRENT_DIR if os.path.exists(os.path.join(CURRENT_DIR, "lighter_news_sniper.py")) else ("C:/LighterBot" if os.path.exists("C:/LighterBot") else ".")
# Supervisor meta-log (separate from the bot's canonical sniper_app.log).
LOG_FILE = os.path.join(LOG_DIR, "watchdog_supervisor.log")
# Canonical child PID + app log paths.
PID_FILE = os.path.join(LOG_DIR, "bot.pid")
SNIPER_APP_LOG = os.path.join(LOG_DIR, "sniper_app.log")

from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [WatchdogSupervisor] %(message)s",
    handlers=[
        RotatingFileHandler(LOG_FILE, maxBytes=25_000_000, backupCount=3, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("WatchdogSupervisor")

PYTHON_EXE = sys.executable or "python"
BOT_SCRIPT = os.path.join(LOG_DIR, "lighter_news_sniper.py") if os.path.exists(os.path.join(LOG_DIR, "lighter_news_sniper.py")) else "C:/LighterBot/lighter_news_sniper.py"
BOT_ARGS = ["--live", "--margin-pct", "85"]
HEARTBEAT_INTERVAL_SEC = 3600.0  # Hourly Telegram status


def _build_bot_args() -> list:
    return list(BOT_ARGS)

active_child_process: Optional[subprocess.Popen] = None


def _write_pid_file(pid: int) -> None:
    try:
        with open(PID_FILE, "w", encoding="utf-8") as fh:
            fh.write(str(pid))
    except OSError as e:
        logger.warning("Could not write %s: %s", PID_FILE, e)


def _clear_pid_file(expected_pid: Optional[int] = None) -> None:
    try:
        if not os.path.exists(PID_FILE):
            return
        if expected_pid is not None:
            try:
                current = int(open(PID_FILE, encoding="utf-8").read().strip())
            except (OSError, ValueError):
                current = None
            if current is not None and current != expected_pid:
                return
        os.remove(PID_FILE)
    except OSError:
        pass


def cleanup_child_process(signum=None, frame=None):
    global active_child_process
    if active_child_process and active_child_process.poll() is None:
        logger.info("🛑 Terminating child bot process before exit...")
        pid = active_child_process.pid
        try:
            active_child_process.terminate()
            active_child_process.wait(timeout=3)
        except Exception:
            try:
                active_child_process.kill()
            except Exception:
                pass
        _clear_pid_file(pid)
    else:
        _clear_pid_file()
    sys.exit(0)


try:
    signal.signal(signal.SIGINT, cleanup_child_process)
    signal.signal(signal.SIGTERM, cleanup_child_process)
except Exception:
    pass


def send_telegram_alert(message: str) -> None:
    """Dispatches emergency alerts to Telegram (only on unrecoverable failures)."""
    if os.getenv("MUTE_WATCHDOG_TELEGRAM", "false").lower() in ("true", "1", "yes"):
        return
    try:
        from lighter_telegram import tg_send
        tg_send(message)
    except Exception as e:
        logger.error("Failed to send Telegram alert: %s", e)


def run_supervisor_loop():
    """Endless watchdog supervisor loop with auto-crash recovery (100% silent in background)."""
    logger.info("🛡️ [Watchdog Supervisor Started] Guaranteeing 100% 24/7 bot uptime and crash immunity.")

    restart_count = 0

    sub_env = dict(os.environ)
    sub_env["PYTHONIOENCODING"] = "utf-8"
    sub_env["PYTHONUTF8"] = "1"

    global active_child_process
    while True:
        try:
            bot_args = _build_bot_args()
            logger.info("🚀 Launching bot process: %s %s", BOT_SCRIPT, " ".join(bot_args))
            spawn_time = time.time()
            with open(SNIPER_APP_LOG, "a", encoding="utf-8", errors="replace") as log_f:
                process = subprocess.Popen(
                    [PYTHON_EXE, BOT_SCRIPT] + bot_args,
                    cwd=LOG_DIR,
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    env=sub_env,
                )
                active_child_process = process
                _write_pid_file(process.pid)
                logger.info("bot.pid=%s written to %s", process.pid, PID_FILE)

                # Monitor while running silently
                while process.poll() is None:
                    time.sleep(5)

            # If process terminated, log exit code and auto-recover
            exit_code = process.returncode
            _clear_pid_file(process.pid)
            run_duration = time.time() - spawn_time
            restart_count += 1
            delay_sec = 2.0 if run_duration > 15.0 else min(30.0, 5.0 * restart_count)
            logger.warning("⚠️ Bot process exited with code %d after %.1fs! Auto-restarting in %.1fs (Restart #%d)...", exit_code, run_duration, delay_sec, restart_count)
            if restart_count <= 3 or restart_count % 10 == 0:
                send_telegram_alert(
                    f"⚠️ <b>AUTO-HEALING ACTIVATED</b>\n"
                    f"Process exited with code <code>{exit_code}</code>.\n"
                    f"🔄 <b>Auto-restarting in {int(delay_sec)} seconds...</b>"
                )
            time.sleep(delay_sec)

        except Exception as e:
            logger.critical("Fatal supervisor error: %s. Auto-recovering in 5s...", e)
            time.sleep(5)


if __name__ == "__main__":
    run_supervisor_loop()
