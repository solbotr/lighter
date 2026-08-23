#!/usr/bin/env python3
"""
Unit Tests for Phase 12 Institutional Upgrades (test_institutional_frontier_v7.py)
=================================================================================
1. Whale Copy-Trading & Smart Money Follower (whale_copy_trader.py)
2. Liquidation Cascade Hunter (liquidation_hunter.py)
3. Statistical Pairs & Cointegration Mean-Reversion (stat_arb_pairs.py)
4. Market Regime & Fear/Greed Posture Switch (market_regime_adapter.py)
5. Multi-DEX Unified Smart Router (multi_dex_router.py)
"""

from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from whale_copy_trader import WhaleCopyTraderEngine, WhaleSignalType, WhaleTradeMirrorPlan
from liquidation_hunter import LiquidationHunterEngine, LiquidationSide, LiquidationSnipeOrder
from stat_arb_pairs import StatisticalArbitragePairEngine, PairAction
from market_regime_adapter import MarketRegimeAdapter, MarketRegime, RegimeParameters
from multi_dex_router import MultiDEXUnifiedRouter, DEXVenue, VenueExecutionQuote


def test_whale_copy_trader_detection_and_mirror():
    received_plans = []
    engine = WhaleCopyTraderEngine(
        min_whale_notional_usd=250000.0,
        my_copy_capital_usd=100.0,
        on_mirror_signal=lambda p: received_plans.append(p),
    )

    # Whale opens a $500k SOL Long
    pos_data = {
        "szi": 2500.0,
        "entryPx": 200.0,
        "leverage": {"value": 5.0},
    }
    plan = engine.evaluate_whale_position_change(
        whale_address="0x5055fc18dbd809559c7becc3e9f50e93eb220807",
        asset="SOL",
        current_pos=pos_data,
        alias="Leaderboard #1 Whale",
    )
    assert plan is not None
    assert plan.signal_type == WhaleSignalType.POSITION_OPENED
    assert plan.side == "BUY"
    assert plan.whale_notional_usd == 500000.0
    assert len(received_plans) == 1
    assert "SOL" in engine.active_mirrored_positions

    # Whale closes position
    close_data = {"szi": 0.0, "entryPx": 200.0}
    close_plan = engine.evaluate_whale_position_change(
        whale_address="0x5055fc18dbd809559c7becc3e9f50e93eb220807",
        asset="SOL",
        current_pos=close_data,
    )
    assert close_plan is not None
    assert close_plan.signal_type == WhaleSignalType.POSITION_CLOSED
    assert "SOL" not in engine.active_mirrored_positions


def test_liquidation_cascade_hunter_discount_snipe():
    engine = LiquidationHunterEngine(
        min_notional_usd=100.0,
        min_discount_bps=25.0,
        target_profit_bps=50.0,
    )

    # Long liquidated in flash crash (bankruptcy px 195.0, mark px 200.0 -> 2.5% discount)
    snipe = engine.evaluate_liquidation(
        event_id="liq_1",
        symbol="SOL",
        side=LiquidationSide.LONG_LIQUIDATED,
        bankruptcy_price=195.0,
        mark_price=200.0,
        size_base=10.0,
    )
    assert snipe is not None
    assert snipe.action == "BUY"
    assert snipe.discount_bps == 250.0
    assert snipe.target_exit_price > snipe.snipe_price


def test_statistical_pairs_z_score_divergence():
    engine = StatisticalArbitragePairEngine(
        lookback_periods=30,
        entry_z_threshold=2.0,
    )

    # Feed steady ratio of 10.0 for 25 periods
    for _ in range(25):
        engine.update_prices("SOL", 200.0, "ETH", 20.0)

    # Sudden divergence: SOL drops to 150.0 (Ratio 7.5 -> Z <= -2.0)
    opp = engine.update_prices("SOL", 150.0, "ETH", 20.0)
    assert opp is not None
    assert opp.action == PairAction.LONG_A_SHORT_B
    assert opp.z_score < -1.5


def test_market_regime_adapter_classification():
    adapter = MarketRegimeAdapter()

    # Extreme volatility
    res1 = adapter.classify_regime(fng_value=50, avg_funding_apr=0.10, volatility_multiplier=2.5)
    assert res1.regime == MarketRegime.EXTREME_VOLATILITY
    assert res1.sl_multiplier < 1.0  # Tighter SL

    # Bull momentum
    res2 = adapter.classify_regime(fng_value=75, avg_funding_apr=0.25, volatility_multiplier=1.2)
    assert res2.regime == MarketRegime.BULL_MOMENTUM
    assert res2.tp_multiplier > 1.5  # Wider TP

    # Bear dump
    res3 = adapter.classify_regime(fng_value=25, avg_funding_apr=-0.15, volatility_multiplier=1.2)
    assert res3.regime == MarketRegime.BEAR_DUMP


def test_multi_dex_router_routing():
    router = MultiDEXUnifiedRouter()

    # Without Hyperliquid auth -> 100% routed to zkLighter
    dec = router.route_trade("BTC", "BUY", 500.0)
    assert dec.primary_venue == DEXVenue.ZKLIGHTER
    assert dec.primary_notional_usd == 500.0
    assert dec.secondary_venue is None

    # Update live quotes
    router.update_venue_quote(
        VenueExecutionQuote(
            venue=DEXVenue.ZKLIGHTER,
            symbol="BTC",
            side="BUY",
            best_bid=95000.0,
            best_ask=95010.0,
            depth_bid_usd=10000.0,
            depth_ask_usd=10000.0,
            fee_maker_bps=0.0,
            fee_taker_bps=2.0,
            latency_ms=1.2,
        )
    )
    assert "BTC" in router.quotes_cache
