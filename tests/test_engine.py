from datetime import datetime, timezone, timedelta

from lighter_news.engine import NewsTradingEngine
from lighter_news.models import Direction, MarketSnapshot, NewsEvent
from lighter_news.risk import RiskEngine, RiskLimits
from lighter_news.news import NewsDeduplicator


def event(title: str, entities=frozenset({"HYPE"})) -> NewsEvent:
    now = datetime.now(timezone.utc)
    return NewsEvent(
        id="e1",
        title=title,
        source="Reuters",
        published_at=now,
        entities=entities,
    )


def market() -> MarketSnapshot:
    return MarketSnapshot(
        symbol="HYPE", mid=50, bid=49.99, ask=50.01,
        return_1m=0.01, return_5m=0.015,
        spread_bps=4, liquidity_usd=1_000_000,
    )


def test_duplicate_headline_is_rejected():
    d = NewsDeduplicator()
    e = event("President mentions Hyperliquid")
    assert d.accept(e)
    assert not d.accept(e)


def test_engine_requires_asset_entity():
    engine = NewsTradingEngine()
    assert engine.process(event("Bitcoin news", frozenset({"BTC"})), {"HYPE": market()}) == []


def test_bullish_signal_scores_above_zero():
    engine = NewsTradingEngine()
    signals = engine.process(event("President announces support and adoption for Hyperliquid"), {"HYPE": market()})
    assert signals
    assert signals[0].direction is Direction.LONG
    assert signals[0].score > 0


def test_risk_rejects_wide_spread():
    risk = RiskEngine(RiskLimits(max_spread_bps=10))
    signal = NewsTradingEngine().process(event("Hyperliquid gets support"), {"HYPE": market()})[0]
    wide = market().model_copy(update={"spread_bps": 100})
    decision = risk.evaluate(signal, wide, 100)
    assert not decision.approved


def test_old_news_has_zero_or_low_novelty():
    old = event("Hyperliquid gets support").model_copy(
        update={"published_at": datetime.now(timezone.utc) - timedelta(minutes=10)}
    )
    signals = NewsTradingEngine().process(old, {"HYPE": market()})
    assert signals[0].novelty == 0
