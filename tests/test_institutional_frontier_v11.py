#!/usr/bin/env python3
"""
Unit Tests for Phase 16 Quant Engines (test_institutional_frontier_v11.py)
===========================================================================
1. Kyle's Lambda Microstructure Price Impact Estimator (kyles_lambda_impact.py)
2. State-Space Kalman Filter Fair Value Tracker (kalman_fair_value.py)
3. Institutional Liquidity Wall Breakout Sweeper (liquidity_wall_sweeper.py)
4. Cross-Asset Granger Causality Lead-Lag Network (granger_causality_network.py)
5. Dynamic Portfolio High-Water Mark & Drawdown Brake (drawdown_brake_vault.py)
"""

from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kyles_lambda_impact import KylesLambdaImpactEstimator
from kalman_fair_value import KalmanFairValueTracker
from liquidity_wall_sweeper import LiquidityWallBreakoutSweeper
from granger_causality_network import GrangerCausalityNetwork
from drawdown_brake_vault import DrawdownBrakeVault


def test_kyles_lambda_impact_estimation():
    estimator = KylesLambdaImpactEstimator(rolling_window=20, max_allowable_impact_bps=20.0)

    # Register 10 trade observations: $10,000 order moves price by ~0.50 bps
    for _ in range(10):
        estimator.register_trade_observation("SOL", order_flow_usd=10000.0, price_change_bps=0.50)

    estimate = estimator.estimate_order_impact("SOL", requested_size_usd=200.0)
    assert estimate.lambda_impact_coefficient > 0.0
    assert estimate.expected_impact_bps < 1.0
    assert estimate.max_safe_size_usd > 1000.0


def test_kalman_fair_value_tracker():
    tracker = KalmanFairValueTracker()

    # Ingest Binance clean mark price
    s1 = tracker.update_venue_price("BTC", "BINANCE", 95000.0)
    assert s1.estimated_fair_value == 95000.0

    # Ingest noisy zkLighter price lagging below at 94,800 -> Triggers undervalued buy
    s2 = tracker.update_venue_price("BTC", "ZKLIGHTER", 94800.0)
    assert s2.latest_z_score < 0.0


def test_liquidity_wall_breakout_sweeper():
    sweeper = LiquidityWallBreakoutSweeper(min_wall_notional_usd=100000.0, erosion_threshold_pct=70.0)

    # 1. Detect large resting ask wall of $150,000 at $200.0
    sig1 = sweeper.update_orderbook_wall("SOL", side="ASK", price=200.0, current_size_usd=150000.0)
    assert sig1 is None

    # 2. Wall rapidly eroded to $30,000 (80% eaten) -> Fires breakout signal
    sig2 = sweeper.update_orderbook_wall("SOL", side="ASK", price=200.0, current_size_usd=30000.0)
    assert sig2 is not None
    assert sig2.direction == "BUY_BREAKOUT"
    assert sig2.wall_price == 200.0


def test_granger_causality_network():
    network = GrangerCausalityNetwork()

    # Push 15 correlated returns
    for i in range(15):
        network.push_return("SOL", return_bps=5.0 + i)
        network.push_return("HYPE", return_bps=4.0 + i)

    rel = network.evaluate_lead_lag("SOL", "HYPE")
    assert rel is not None
    assert rel.is_statistically_significant is True
    assert rel.optimal_lag_ms > 0.0


def test_drawdown_brake_vault():
    vault = DrawdownBrakeVault(initial_capital_usd=1000.0, soft_brake_drawdown_pct=2.0, hard_brake_drawdown_pct=4.0)

    # 1. Normal state ($1,000 equity)
    s1 = vault.update_portfolio_equity(1000.0)
    assert s1.is_soft_brake_active is False
    assert s1.sizing_scaler == 1.0

    # 2. New high-water mark at $1,200 -> sweeps 20% ($40) into cold vault
    s2 = vault.update_portfolio_equity(1200.0)
    assert s2.vaulted_profit_usd == 40.0
    assert s2.high_water_mark_usd == 1200.0

    # 3. Soft brake triggered: Equity drops to $1,170 (-2.5% dd from $1,200 HWM) -> 50% size
    s3 = vault.update_portfolio_equity(1170.0)
    assert s3.is_soft_brake_active is True
    assert s3.sizing_scaler == 0.50

    # 4. Hard stop triggered: Equity drops to $1,140 (-5.0% dd from $1,200 HWM) -> 0% size
    s4 = vault.update_portfolio_equity(1140.0)
    assert s4.is_hard_brake_active is True
    assert s4.sizing_scaler == 0.0
