#!/usr/bin/env python3
"""Supervise the live sniper and optional market-maker processes."""

from __future__ import annotations

import logging
import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = CURRENT_DIR if os.path.exists(os.path.join(CURRENT_DIR, "lighter_news_sniper.py")) else ("C:/LighterBot" if os.path.exists("C:/LighterBot") else ".")
LOG_FILE = os.path.join(LOG_DIR, "watchdog_supervisor.log")
PID_FILE = os.path.join(LOG_DIR, "bot.pid")
SNIPER_APP_LOG = os.path.join(LOG_DIR, "sniper_app.log")
PYTHON_EXE = sys.executable or "python"
BOT_SCRIPT = os.path.join(LOG_DIR, "lighter_news_sniper.py") if os.path.exists(os.path.join(LOG_DIR, "lighter_news_sniper.py")) else "C:/LighterBot/lighter_news_sniper.py"
BOT_ARGS = ["--live", "--margin-pct", "85"]
HEARTBEAT_INTERVAL_SEC = 3600.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [WatchdogSupervisor] %(message)s",
    handlers=[RotatingFileHandler(LOG_FILE, maxBytes=25_000_000, backupCount=3, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("WatchdogSupervisor")


@dataclass(frozen=True)
class ManagedProcess:
    name: str
    script: str
    args: list[str]
    pid_file: str
    log_file: str
    enabled: bool = True


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _build_bot_args() -> list[str]:
    return list(BOT_ARGS)


def _build_managed_processes() -> list[ManagedProcess]:
    processes = [ManagedProcess("sniper", BOT_SCRIPT, _build_bot_args(), PID_FILE, SNIPER_APP_LOG)]
    if _truthy(os.getenv("MM_ENABLED", "0")):
        processes.append(ManagedProcess(
            "mm",
            os.path.join(LOG_DIR, "lighter_mm_bot.py"),
            shlex.split(os.getenv("MM_BOT_ARGS", "--live"), posix=os.name != "nt"),
            os.path.join(LOG_DIR, "mm_bot.pid"),
            os.path.join(LOG_DIR, "mm_app.log"),
        ))
    return processes


# Kept for compatibility with operators that inspect this module attribute.
active_child_process: Optional[subprocess.Popen] = None
active_child_processes: dict[str, subprocess.Popen] = {}


def _write_pid_file(path: str, pid: int) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(str(pid))
    except OSError as exc:
        logger.warning("Could not write %s: %s", path, exc)


def _clear_pid_file(path: str, expected_pid: Optional[int] = None) -> None:
    try:
        if not os.path.exists(path):
            return
        if expected_pid is not None:
            with open(path, encoding="utf-8") as fh:
                current = int(fh.read().strip())
            if current != expected_pid:
                return
        os.remove(path)
    except (OSError, ValueError):
        pass


def cleanup_child_process(signum=None, frame=None):
    """Terminate every managed child and clear only its matching PID file."""
    for config in _build_managed_processes():
        process = active_child_processes.get(config.name)
        if process is not None and process.poll() is None:
            logger.info("Terminating %s child process", config.name)
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
            _clear_pid_file(config.pid_file, process.pid)
        else:
            _clear_pid_file(config.pid_file)
    raise SystemExit(0)


try:
    signal.signal(signal.SIGINT, cleanup_child_process)
    signal.signal(signal.SIGTERM, cleanup_child_process)
except Exception:
    pass


def send_telegram_alert(message: str) -> None:
    if _truthy(os.getenv("MUTE_WATCHDOG_TELEGRAM", "false")):
        return
    try:
        from lighter_telegram import tg_send
        tg_send(message)
    except Exception as exc:
        logger.error("Failed to send Telegram alert: %s", exc)


def run_supervisor_loop() -> None:
    """Run all enabled children with independent crash counters and backoff."""
    configs = _build_managed_processes()
    logger.info("Watchdog started for: %s", ", ".join(item.name for item in configs))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    starts: dict[str, float] = {}
    restart_counts = {item.name: 0 for item in configs}
    next_start = {item.name: 0.0 for item in configs}
    log_handles = {}
    global active_child_process

    while True:
        now = time.time()
        for config in configs:
            process = active_child_processes.get(config.name)
            if process is None and now >= next_start[config.name]:
                try:
                    log_handle = open(config.log_file, "a", encoding="utf-8", errors="replace")
                    process = subprocess.Popen([PYTHON_EXE, config.script] + config.args, cwd=LOG_DIR, stdout=log_handle, stderr=subprocess.STDOUT, env=env)
                    log_handles[config.name] = log_handle
                    active_child_processes[config.name] = process
                    if config.name == "sniper":
                        active_child_process = process
                    starts[config.name] = now
                    _write_pid_file(config.pid_file, process.pid)
                    logger.info("Launched %s (pid %s): %s", config.name, process.pid, " ".join(config.args))
                except Exception as exc:
                    if "log_handle" in locals() and not log_handle.closed:
                        log_handle.close()
                    logger.error("Could not launch %s: %s", config.name, exc)
                    next_start[config.name] = now + 5
                continue
            if process is None or process.poll() is None:
                continue

            runtime = now - starts[config.name]
            exit_code = process.returncode
            _clear_pid_file(config.pid_file, process.pid)
            log_handles.pop(config.name, None).close()
            active_child_processes.pop(config.name, None)
            restart_counts[config.name] += 1
            delay = 2.0 if runtime > 15 else min(30.0, 5.0 * restart_counts[config.name])
            next_start[config.name] = now + delay
            logger.warning("%s exited with code %s after %.1fs; restarting in %.1fs", config.name, exit_code, runtime, delay)
            if restart_counts[config.name] <= 3 or restart_counts[config.name] % 10 == 0:
                send_telegram_alert(f"⚠️ <b>{config.name} AUTO-HEALING</b>\nExited with code <code>{exit_code}</code>. Restarting in {int(delay)} seconds.")
        time.sleep(1)


if __name__ == "__main__":
    import socket
    _sup_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _sup_sock.bind(("127.0.0.1", 49200))
    except socket.error:
        print("🚨 [SUPERVISOR LOCK] Another instance of watchdog_supervisor is already running (port 49200 bound). Exiting.")
        sys.exit(0)
    run_supervisor_loop()
