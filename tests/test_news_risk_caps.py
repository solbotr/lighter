import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from lighter_news_risk import LighterNewsRiskGate, MarketSnapshot
from news_pipeline import NormalizedNewsEvent


@dataclass
class Position:
    asset: str
    side: str = "BUY/LONG"
    is_active: bool = True
    notional_usd: float = 0.0
    size_eth: float = 0.0
    entry_price: float = 0.0


def make_event(adapter="treenews_ws", source_id="source", latency=0):
    now = datetime.now(timezone.utc)
    return NormalizedNewsEvent(
        event_id="e", source_id=source_id, publisher="Source", headline="Binance lists ETH",
        body="official listing", url="https://example.test", guid="g",
        published_at=now - timedelta(seconds=latency), ingested_at=now, source_score=0.9,
        category="official", content_hash="h", entities=("ETH",), event_type="listing",
        direction="BULLISH", confidence=0.9, materiality=0.8, raw={"adapter": adapter},
    )


def approve(gate, positions, requested=50, collateral=None, event=None, entry_mode="news"):
    return asyncio.run(gate.approve(
        event or make_event(), MarketSnapshot("ETH", 2500), requested, confirmed=True,
        asset="ETH", side="BUY/LONG", collateral_usd=collateral,
        active_positions={str(i): p for i, p in enumerate(positions)}, entry_mode=entry_mode,
    ))


def test_open_positions_apply_to_aggregate_cap(monkeypatch):
    monkeypatch.setenv("NEWS_MAX_EXPOSURE_USD", "200")
    monkeypatch.setenv("NEWS_MAX_ASSET_EXPOSURE_USD", "1000")
    monkeypatch.setenv("NEWS_MAX_DIRECTIONAL_USD", "1000")
    gate = LighterNewsRiskGate(live=False)
    assert "aggregate news exposure cap reached" in approve(gate, [Position("BTC", notional_usd=90), Position("SOL", notional_usd=90)]).reasons
    assert approve(LighterNewsRiskGate(live=False), [Position("BTC", notional_usd=90)]).approved


def test_concurrency_counts_only_active_positions(monkeypatch):
    monkeypatch.setenv("NEWS_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("NEWS_MAX_EXPOSURE_USD", "10000")
    monkeypatch.setenv("NEWS_MAX_DIRECTIONAL_USD", "10000")
    two = [Position("BTC", notional_usd=10), Position("SOL", notional_usd=10)]
    assert "max concurrent positions reached" in approve(LighterNewsRiskGate(live=False), two).reasons
    assert approve(LighterNewsRiskGate(live=False), [two[0], Position("SOL", is_active=False, notional_usd=10)]).approved


def test_gross_leverage_cap(monkeypatch):
    monkeypatch.setenv("NEWS_MAX_TRADE_USD", "250")
    monkeypatch.setenv("NEWS_MAX_EXPOSURE_USD", "10000")
    monkeypatch.setenv("NEWS_MAX_ASSET_EXPOSURE_USD", "10000")
    monkeypatch.setenv("NEWS_MAX_DIRECTIONAL_USD", "10000")
    monkeypatch.setenv("NEWS_RISK_PER_TRADE_PCT", "100")
    monkeypatch.setenv("NEWS_MAX_GROSS_LEVERAGE", "1.5")
    positions = [Position("BTC", notional_usd=900)]
    assert "gross leverage cap reached" in approve(LighterNewsRiskGate(live=False), positions, 200, 700).reasons
    monkeypatch.setenv("NEWS_MAX_GROSS_LEVERAGE", "2.0")
    assert approve(LighterNewsRiskGate(live=False), positions, 200, 700).approved


def test_source_allowlist_and_latency(monkeypatch):
    monkeypatch.setenv("NEWS_MAX_EXPOSURE_USD", "10000")
    # Allowlist removed — any adapter (including rss) may trade live.
    assert approve(LighterNewsRiskGate(live=False), [], event=make_event()).approved
    assert approve(LighterNewsRiskGate(live=False), [], event=make_event("rss")).approved
    monkeypatch.setenv("NEWS_MAX_FEED_LATENCY_SEC", "20")
    stale = approve(LighterNewsRiskGate(live=False), [], event=make_event(latency=60))
    assert not stale.approved and "feed latency 60s" in " ".join(stale.reasons)
    assert approve(LighterNewsRiskGate(live=False), [], event=make_event("rss"), entry_mode="manual").approved