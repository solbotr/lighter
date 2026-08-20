import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from lighter_trader.config import Settings
from lighter_trader.domain import Direction, MarketSnapshot, PortfolioState, Signal
from lighter_trader.execution.compatibility import EXPECTED_SDK_VERSION, check_sdk_compatibility
from lighter_trader.execution.controls import KillSwitch
from lighter_trader.execution.lighter_adapter import LiveExecutionDisabled, build_market_order_request
from lighter_trader.execution.manual_gate import ManualLiveApproval
from lighter_trader.execution.paper import OrderIntent
from lighter_trader.execution.reconciliation import ReconciliationSnapshot, reconcile_expected_orders
from lighter_trader.execution.live_readonly import AccountSnapshot


def test_sdk_compatibility_is_current():
    report = check_sdk_compatibility()
    assert report.compatible, report.failures
    assert report.sdk_version == EXPECTED_SDK_VERSION


def test_order_request_is_non_transmitting_and_deterministic():
    intent = OrderIntent(1, "buy", 10.0, "signal-1")
    first = build_market_order_request(intent, client_order_index=10, base_amount=100, avg_execution_price=1000)
    second = build_market_order_request(intent, client_order_index=10, base_amount=100, avg_execution_price=1000)
    assert first == second
    assert first.is_ask is False


def test_invalid_order_request_rejected():
    with pytest.raises(ValueError):
        build_market_order_request(OrderIntent(0, "buy", 10, "s"), client_order_index=1, base_amount=1, avg_execution_price=1)


def test_manual_approval_requires_identity_and_reference():
    with pytest.raises(ValueError):
        ManualLiveApproval.issue("", "review")
    with pytest.raises(ValueError):
        ManualLiveApproval.issue("operator", "")
    approval = ManualLiveApproval.issue("operator", "change-123")
    assert approval.review_reference == "change-123"


def test_reconciliation_detects_unknown_status_and_is_deterministic():
    now = datetime.now(timezone.utc)
    account = AccountSnapshot(1, Decimal("1000"), Decimal("900"), (), now)
    from lighter_trader.execution.live_readonly import OpenOrderSnapshot
    order = OpenOrderSnapshot(1, 1, "o", "c", 1, "buy", "mystery", Decimal("1"), Decimal("0"), False)
    result = reconcile_expected_orders([], account, (order,), "now")
    assert not result.healthy
    assert "unknown_order_status:mystery" in result.discrepancies


def test_live_submit_remains_disabled_after_all_gates(tmp_path):
    from lighter_trader.execution.coordinator import GuardedLiveCoordinator, Preflight
    now = datetime.now(timezone.utc)
    settings = Settings(mode="live", base_url="https://mainnet.zklighter.elliot.ai", poll_interval_seconds=1)
    account = AccountSnapshot(1, Decimal("1000"), Decimal("900"), (), now)
    reconciliation = ReconciliationSnapshot(account, (), (), now.isoformat())
    coordinator = GuardedLiveCoordinator(settings, KillSwitch(tmp_path / "kill.json"), ManualLiveApproval.issue("operator", "review-1"))
    coordinator.set_preflight(Preflight(now, reconciliation))
    signal = Signal("s", "e", "BTC", Direction.LONG, .9, .9, now, now + timedelta(minutes=1))
    market = MarketSnapshot("BTC", now, 100, 101, 100, 1000, .01)
    with pytest.raises(LiveExecutionDisabled, match="remains disabled"):
        coordinator.submit(OrderIntent(1, "buy", 10, "s"), signal=signal, market=market, portfolio=PortfolioState(1000))
