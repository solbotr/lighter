import asyncio
import pytest
from lighter_news_risk import MacroRegimeGuard, LighterNewsRiskGate, MarketSnapshot
from news_pipeline import NormalizedNewsEvent
from datetime import datetime, timezone


def test_macro_regime_guard_blocks_altcoin_long_during_btc_dump():
    guard = MacroRegimeGuard()
    guard.update_btc_price(price=76000.0, change_15m=-0.60, change_1h=-1.20)
    
    # 1. Altcoin BUY/LONG should be vetoed
    ok, reason = guard.evaluate_regime('SOL', 'BUY/LONG', confidence=0.75)
    assert not ok
    assert 'BTC is dumping' in reason
    assert 'blocking counter-trend altcoin LONG' in reason

    # 2. Altcoin SELL/SHORT should be approved (aligned with trend)
    ok_short, reason_short = guard.evaluate_regime('SOL', 'SELL/SHORT', confidence=0.75)
    assert ok_short
    assert reason_short == ''

    # 3. BTC itself should bypass
    ok_btc, _ = guard.evaluate_regime('BTC', 'BUY/LONG', confidence=0.75)
    assert ok_btc

    # 4. Tier-1 high conviction (>=0.90) should bypass
    ok_tier1, _ = guard.evaluate_regime('SOL', 'BUY/LONG', confidence=0.95)
    assert ok_tier1

    # 5. Catalyst class TIER1 should bypass
    ok_class, _ = guard.evaluate_regime('SOL', 'BUY/LONG', confidence=0.75, catalyst_class='TIER1')
    assert ok_class


def test_macro_regime_guard_blocks_altcoin_short_during_btc_pump():
    guard = MacroRegimeGuard()
    guard.update_btc_price(price=78000.0, change_15m=+0.80, change_1h=+1.50)

    # 1. Altcoin SELL/SHORT should be vetoed
    ok, reason = guard.evaluate_regime('AVAX', 'SELL/SHORT', confidence=0.75)
    assert not ok
    assert 'BTC is surging' in reason
    assert 'blocking counter-trend altcoin SHORT' in reason

    # 2. Altcoin BUY/LONG should be approved
    ok_long, reason_long = guard.evaluate_regime('AVAX', 'BUY/LONG', confidence=0.75)
    assert ok_long
    assert reason_long == ''


def test_macro_regime_guard_integration_with_risk_gate():
    gate = LighterNewsRiskGate(live=False)
    gate.macro_guard.update_btc_price(price=76000.0, change_15m=-0.55, change_1h=-1.10)
    now = datetime.now(timezone.utc)

    event = NormalizedNewsEvent(
        event_id='event-1', source_id='source', publisher='Source', headline='Routine partnership for SOL', body='official',
        url='https://example.test', guid='g', published_at=now, ingested_at=now, source_score=0.9,
        category='official', content_hash='hash', entities=('SOL',), event_type='partnership', direction='BULLISH',
        confidence=0.75, materiality=0.8, raw={'adapter': 'treenews_ws'},
    )

    decision = asyncio.run(gate.approve(
        event=event,
        snapshot=MarketSnapshot('SOL', 100.0),
        requested_usd=200.0,
        confirmed=False,
        side='BUY',
        collateral_usd=1000.0,
    ))

    assert not decision.approved
    assert any('macro regime veto' in r for r in decision.reasons)
