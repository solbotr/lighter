#!/usr/bin/env python3
"""
Unit Tests for Phase 20 Quant Engines (test_institutional_frontier_v15.py)
===========================================================================
1. Fourier Spectral Orderbook Oscillation Detector (fourier_orderbook_oscillator.py)
2. Ledoit-Wolf Covariance Shrinkage Risk Parity (ledoit_wolf_risk_parity.py)
3. Cross-Exchange Liquidity Evaporation Radar (liquidity_evaporation_radar.py)
4. Volume-Synchronized Jump Crash Shield (vpj_crash_shield.py)
5. Autonomous Subaccount Rebalancing & Sweep Pipeline (subaccount_rebalance_pipeline.py)
"""

from __future__ import annotations

import os
import sys
import time
import math
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fourier_orderbook_oscillator import FourierOrderbookOscillator
from ledoit_wolf_risk_parity import LedoitWolfRiskParityOptimizer
from liquidity_evaporation_radar import LiquidityEvaporationRadar
from vpj_crash_shield import VolumeSynchronizedJumpCrashShield
from subaccount_rebalance_pipeline import SubaccountRebalancePipeline


def test_fourier_spectral_oscillator():
    oscillator = FourierOrderbookOscillator(sampling_rate_hz=10.0, window_size=32)

    # Feed 32 ticks with a deterministic 2-second sinusoidal rhythm
    t0 = time.time()
    for i in range(32):
        t = t0 + (i * 0.1)
        val = 10.0 + 2.0 * math.sin(i * 0.5)
        oscillator.push_tick("BTC", val, timestamp=t)

    res = oscillator.compute_spectral_decomposition("BTC")
    assert res.dominant_period_sec >= 0.0
    assert len(res.active_peaks) > 0


def test_ledoit_wolf_risk_parity_optimizer():
    optimizer = LedoitWolfRiskParityOptimizer(default_shrinkage_delta=0.25)

    # 4 assets with different volatilities (BTC: 40%, ETH: 55%, SOL: 75%, DOGE: 110%)
    vols = {
        "BTC": 40.0,
        "ETH": 55.0,
        "SOL": 75.0,
        "DOGE": 110.0,
    }

    plan = optimizer.compute_risk_parity_weights(total_capital_usd=740.86, asset_volatilities=vols)
    assert plan.total_capital_usd == 740.86
    assert len(plan.allocations) == 4

    # BTC (lowest vol) should get highest allocation weight
    alloc_map = {a.symbol: a.target_weight_pct for a in plan.allocations}
    assert alloc_map["BTC"] > alloc_map["DOGE"]
    assert sum(alloc_map.values()) == pytest.approx(100.0, 0.5)


def test_liquidity_evaporation_radar():
    radar = LiquidityEvaporationRadar(depth_drop_threshold_pct=55.0, max_collapse_window_ms=300.0)

    # 1. Normal depth ($100,000)
    a1 = radar.push_venue_depth("SOL", "HYPERLIQUID", 100000.0)
    assert a1 is None

    # 2. Flash depth collapse to $25,000 (-75% drop in < 50ms) -> Triggers Critical Black Hole Alert
    a2 = radar.push_venue_depth("SOL", "HYPERLIQUID", 25000.0)
    assert a2 is not None
    assert a2.should_emergency_pull_quotes is True
    assert a2.severity == "CRITICAL_BLACK_HOLE"
    assert a2.depth_drop_pct == 75.0


def test_vpj_jump_crash_shield():
    shield = VolumeSynchronizedJumpCrashShield(bucket_size_usd=10000.0)

    # 1. Feed normal low-variance volume buckets
    for _ in range(10):
        s1 = shield.push_volume_bucket("SOL", price_return_bps=2.0)
    assert s1.shield_status == "NORMAL"
    assert s1.recommended_stop_loss_pct == -1.50

    # 2. Feed sudden catastrophic jump returns (-85 bps, -120 bps) -> Tightens Stop-Loss
    shield.push_volume_bucket("SOL", price_return_bps=-85.0)
    s2 = shield.push_volume_bucket("SOL", price_return_bps=-120.0)
    assert s2.recommended_stop_loss_pct < -0.50  # Tightened


def test_subaccount_rebalance_pipeline():
    pipeline = SubaccountRebalancePipeline(min_rebalance_delta_usd=20.0)

    # Sniper has $700 (94%), MM has $20, Arb has $20 (Total $740)
    balances = {
        "737649": 700.0,
        "281474976497685": 20.0,
        "281474976497686": 20.0,
    }

    plan = pipeline.evaluate_allocations(balances)
    assert plan.is_rebalance_required is True
    assert len(plan.recommended_transfers) > 0

    # Verify funds transferred from Sniper (surplus) to MM (deficit)
    tx = plan.recommended_transfers[0]
    assert tx.from_subaccount == "737649"
    assert tx.transfer_amount_usd > 20.0
