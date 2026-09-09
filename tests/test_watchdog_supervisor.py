#!/usr/bin/env python3
"""
Unit Tests for Watchdog Supervisor (watchdog_supervisor.py)
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from watchdog_supervisor import _build_bot_args, _build_managed_processes, send_telegram_alert


def test_watchdog_supervisor_alert(monkeypatch):
    # Verify send_telegram_alert handles exceptions safely without crashing
    def mock_tg_send(msg):
        assert "TEST" in msg
        return True

    monkeypatch.setattr("lighter_telegram.tg_send", mock_tg_send)
    send_telegram_alert("TEST ALERT")


def test_watchdog_bot_args_are_live_only():
    args = _build_bot_args()
    assert "--live" in args
    assert "--paper" not in args


def test_managed_processes_mm_is_opt_in(monkeypatch):
    monkeypatch.delenv("MM_ENABLED", raising=False)
    assert [process.name for process in _build_managed_processes()] == ["sniper"]

    monkeypatch.setenv("MM_ENABLED", "1")
    processes = _build_managed_processes()
    assert [process.name for process in processes] == ["sniper", "mm"]
    mm = processes[1]
    assert "--live" in mm.args
    assert mm.pid_file != processes[0].pid_file
    assert mm.log_file != processes[0].log_file
