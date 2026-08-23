#!/usr/bin/env python3
"""
Unit Tests for Phase 19 Quant Engines (test_institutional_frontier_v14.py)
===========================================================================
1. Limit Order Book Queue Priority & Fill Estimator (queue_priority_estimator.py)
2. Lee-Ready Trade Classifier & Bulk Volume Engine (lee_ready_trade_classifier.py)
3. Multi-Timeframe Volatility Cone Grid Banding (volatility_cone_grid.py)
4. On-Chain Liquidation Cascade Front-Runner (liquidation_frontrunner.py)
5. PnL-Preserving Daily Trailing Ratchet Vault (trailing_ratchet_vault.py)
"""

from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from queue_priority_estimator import OrderbookQueuePriorityEstimator
from lee_ready_trade_classifier import LeeReadyTradeClassifier
from volatility_cone_grid import VolatilityConeGridEngine
from liquidation_frontrunner import LiquidationCascadeFrontrunner
from trailing_ratchet_vault import TrailingRatchetVault


def test_queue_priority_and_fill_estimator():
    estimator = OrderbookQueuePriorityEstimator(
        fill_arrival_rate_usd_per_sec=10000.0,
        cancel_rate_usd_per_sec=5000.0,
        reprice_queue_threshold_usd=30000.0,
    )

    # 1. Order at top of queue ($500 ahead)
    res_top = estimator.estimate_order_queue(
        order_id="ord_1",
        symbol="BTC",
        side="BID",
        price=95000.0,
        order_size_usd=5000.0,
        queue_ahead_usd=500.0,
        total_level_depth_usd=10000.0,
    )
    assert res_top.is_top_of_queue is True
    assert res_top.fill_probability_pct > 80.0
    assert res_top.should_reprice is False

    # 2. Order deeply queued ($50,000 ahead) -> Flags reprice
    res_deep = estimator.estimate_order_queue(
        order_id="ord_2",
        symbol="BTC",
        side="BID",
        price=95000.0,
        order_size_usd=5000.0,
        queue_ahead_usd=50000.0,
        total_level_depth_usd=60000.0,
    )
    assert res_deep.is_top_of_queue is False
    assert res_deep.should_reprice is True


def test_lee_ready_trade_classifier():
    classifier = LeeReadyTradeClassifier(rolling_window=20, sweep_threshold_usd=20000.0)

    # 1. Trade executed above mid price ($200.50 vs mid $200.00) -> BUY
    t1 = classifier.classify_trade(
        trade_id="tr_1", symbol="SOL", price=200.50, size_usd=5000.0, best_bid=199.90, best_ask=200.10
    )
    assert t1.classified_side == "BUY"
    assert t1.classification_method == "QUOTE_RULE"

    # 2. Push large institutional sweep trade ($30,000 BUY)
    classifier.classify_trade(
        trade_id="tr_2", symbol="SOL", price=200.80, size_usd=30000.0, best_bid=200.00, best_ask=200.20
    )

    flow = classifier.compute_flow_pressure("SOL")
    assert flow.dominant_side == "AGGRESSIVE_BUY"
    assert flow.is_institutional_sweep is True
    assert flow.taker_buy_ratio_pct > 80.0


def test_volatility_cone_grid_banding():
    engine = VolatilityConeGridEngine(base_grid_spread_pct=0.25)

    # 1. Normal regime (48% vol)
    p_norm = engine.compute_grid_spacing("SOL", observed_1h_vol_pct=48.0)
    assert p_norm.current_regime == "NORMAL"
    assert p_norm.optimal_grid_spacing_pct == pytest.approx(0.25, 0.01)

    # 2. Volatility Compression (15% vol) -> Tightens grid to 0.15%
    p_comp = engine.compute_grid_spacing("SOL", observed_1h_vol_pct=15.0)
    assert p_comp.current_regime == "COMPRESSION"
    assert p_comp.optimal_grid_spacing_pct < 0.20

    # 3. Volatility Expansion (95% vol) -> Expands grid to 0.55%
    p_exp = engine.compute_grid_spacing("SOL", observed_1h_vol_pct=95.0)
    assert p_exp.current_regime == "EXTREME"
    assert p_exp.optimal_grid_spacing_pct > 0.50


def test_liquidation_cascade_frontrunner():
    runner = LiquidationCascadeFrontrunner(min_distressed_notional_usd=20000.0, margin_stress_threshold_pct=85.0)

    # Whale Long position with $50,000 notional at 92% margin stress
    sig = runner.evaluate_position_distress(
        trader_wallet="0xwhale123",
        symbol="SOL",
        side="LONG",
        position_notional_usd=50000.0,
        entry_price=210.0,
        current_price=192.0,
        liquidation_price=190.0,
        margin_ratio_pct=92.0,
    )
    assert sig is not None
    assert sig.distressed_side == "LONG"
    assert sig.counter_trade_side == "BUY"
    assert sig.recommended_entry_price < 190.0  # Overshoot entry wick
    assert sig.target_rebound_tp_price > sig.recommended_entry_price


def test_trailing_ratchet_vault():
    vault = TrailingRatchetVault(session_start_equity_usd=1000.0)

    # 1. Normal state ($1,000 equity)
    s1 = vault.update_session_equity(1000.0)
    assert s1.locked_floor_pnl_pct == 0.0
    assert s1.is_trading_locked_for_session is False

    # 2. Profit surges to +4.5% ($1,045) -> Locks in +3.0% floor ($1,030)
    s2 = vault.update_session_equity(1045.0)
    assert s2.peak_daily_pnl_pct == 4.50
    assert s2.locked_floor_pnl_pct == 3.00
    assert s2.locked_floor_equity_usd == 1030.0
    assert s2.is_trading_locked_for_session is False

    # 3. Afternoon pullback: Equity drops to $1,029 (breaches $1,030 floor) -> Session locked
    s3 = vault.update_session_equity(1029.0)
    assert s3.is_ratchet_floor_breached is True
    assert s3.is_trading_locked_for_session is True
