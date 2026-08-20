from datetime import datetime, timezone

import pytest

from lighter_trader.news.dedupe import DedupeIndex
from lighter_trader.news.models import NewsEvent
from lighter_trader.risk.gates import AccountState, RiskLimits, allow_trade
from lighter_trader.signals.scoring import score_event
from lighter_trader.execution.paper import OrderIntent, PaperExecutor


def event(title="President mentions protocol"):
    return NewsEvent("official", title, datetime.now(timezone.utc), source_score=0.95)


def test_dedupe_rejects_duplicate():
    index = DedupeIndex()
    assert len(index.filter_new([event(), event()])) == 1


def test_score_rejects_priced_in_event():
    signal = score_event(event(), sentiment=1, surprise=1, market_confirmation=1, already_priced_in=0.9)
    assert signal.score == 0


def test_risk_rejects_daily_loss():
    ok, reason = allow_trade(
        AccountState(1000, -25, 0, 50, 1), RiskLimits(), 0.9
    )
    assert not ok
    assert reason == "daily loss limit"


def test_paper_executor_is_idempotent():
    executor = PaperExecutor()
    intent = OrderIntent(1, "buy", 50, "signal-1")
    executor.submit(intent)
    with pytest.raises(ValueError, match="duplicate signal"):
        executor.submit(intent)
