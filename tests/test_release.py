from pathlib import Path

import pytest

from lighter_trader.execution.controls import KillSwitch
from lighter_trader.execution.lighter_adapter import LiveExecutionDisabled, MarketOrderRequest
from lighter_trader.execution.release import ExecutionJournal, ProductionRelease, ReleaseStateError


def request():
    return MarketOrderRequest(1, 22, 1000, 100000, False, False)


def test_release_phases_persist_and_duplicate_ids_are_rejected(tmp_path: Path):
    release = ProductionRelease(ExecutionJournal(tmp_path / "journal.jsonl"))
    prepared = release.prepare("client-1", request())
    assert prepared.phase == "PREPARE"
    release.approve("client-1", "operator", "review-1")
    with pytest.raises(LiveExecutionDisabled):
        release.submit("client-1")
    with pytest.raises(ReleaseStateError, match="already exists"):
        release.prepare("client-1", request())


def test_release_requires_phase_order(tmp_path: Path):
    release = ProductionRelease(ExecutionJournal(tmp_path / "journal.jsonl"))
    with pytest.raises(ReleaseStateError, match="PREPARE"):
        release.approve("missing", "operator", "review")


def test_unknown_response_is_ambiguous_and_fail_closed(tmp_path: Path):
    release = ProductionRelease(ExecutionJournal(tmp_path / "journal.jsonl"))
    release.prepare("client-2", request())
    release.approve("client-2", "operator", "review-2")
    with pytest.raises(LiveExecutionDisabled):
        release.submit("client-2")
    record = release.reconcile("client-2", "unknown")
    assert record.phase == "AMBIGUOUS"


def test_audit_journal_does_not_contain_private_key(tmp_path: Path):
    journal_path = tmp_path / "journal.jsonl"
    release = ProductionRelease(ExecutionJournal(journal_path))
    release.prepare("client-3", request())
    release.approve("client-3", "operator", "review-3")
    text = journal_path.read_text(encoding="utf-8")
    assert "private" not in text.lower()
    assert "token" not in text.lower()


def test_kill_switch_persists_emergency_state(tmp_path: Path):
    switch = KillSwitch(tmp_path / "kill.json")
    switch.activate("reconciliation disagreement")
    assert switch.state().active
    assert switch.state().reason == "reconciliation disagreement"
