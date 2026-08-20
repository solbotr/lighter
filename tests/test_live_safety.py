from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from lighter_trader.config import Settings
from lighter_trader.domain import MarketSnapshot, PortfolioState, Signal, Direction
from lighter_trader.execution.controls import KillSwitch
from lighter_trader.execution.manual_gate import ManualLiveApproval
from lighter_trader.execution.coordinator import GuardedLiveCoordinator, Preflight
from lighter_trader.execution.lighter_adapter import LiveExecutionDisabled
from lighter_trader.execution.live_readonly import AccountSnapshot, OpenOrderSnapshot
from lighter_trader.execution.reconciliation import ReconciliationSnapshot
from lighter_trader.execution.paper import OrderIntent


def settings():
    return Settings(mode="live", poll_interval_seconds=1, market_max_age_seconds=30)


def signal():
    now = datetime.now(timezone.utc)
    return Signal("s1", "e1", "BTC", Direction.LONG, 0.9, 0.9, now, now + timedelta(minutes=1))


def market():
    return MarketSnapshot("BTC", datetime.now(timezone.utc), 100, 101, 100.5, 1000, 0.01)


def healthy_preflight():
    account = AccountSnapshot(1, Decimal("1000"), Decimal("900"), (), datetime.now(timezone.utc))
    return Preflight(datetime.now(timezone.utc), ReconciliationSnapshot(account, (), (), "now"))


def test_coordinator_blocks_without_preflight(tmp_path):
    coordinator = GuardedLiveCoordinator(settings(), KillSwitch(tmp_path / "kill.json"), ManualLiveApproval.issue("operator", "review"))
    with pytest.raises(LiveExecutionDisabled, match="preflight"):
        coordinator.submit(OrderIntent(1, "buy", 10, "s1"), signal=signal(), market=market(), portfolio=PortfolioState(1000))


def test_coordinator_blocks_live_write_even_after_healthy_preflight(tmp_path):
    coordinator = GuardedLiveCoordinator(settings(), KillSwitch(tmp_path / "kill.json"), ManualLiveApproval.issue("operator", "review"))
    coordinator.set_preflight(healthy_preflight())
    with pytest.raises(LiveExecutionDisabled, match="remains disabled"):
        coordinator.submit(OrderIntent(1, "buy", 10, "s1"), signal=signal(), market=market(), portfolio=PortfolioState(1000))


def test_kill_switch_blocks_before_preflight_write(tmp_path):
    switch = KillSwitch(tmp_path / "kill.json")
    switch.activate("emergency")
    coordinator = GuardedLiveCoordinator(settings(), switch)
    coordinator.set_preflight(healthy_preflight())
    with pytest.raises(LiveExecutionDisabled, match="kill switch"):
        coordinator.submit(OrderIntent(1, "buy", 10, "s1"), signal=signal(), market=market(), portfolio=PortfolioState(1000))


def test_reconciliation_discrepancy_blocks_preflight(tmp_path):
    coordinator = GuardedLiveCoordinator(settings(), KillSwitch(tmp_path / "kill.json"))
    account = AccountSnapshot(1, Decimal("1000"), Decimal("900"), (), datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="discrepancies"):
        coordinator.set_preflight(Preflight(datetime.now(timezone.utc), ReconciliationSnapshot(account, (), ("unexpected_order:x",), "now")))
