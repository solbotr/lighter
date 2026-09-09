#!/usr/bin/env python3
"""
Unit Tests for Phase 17 Quant Engines (test_institutional_frontier_v12.py)
===========================================================================
1. Almgren-Chriss Optimal Execution Trajectory (almgren_chriss_execution.py)
2. Roll (1984) Effective Spread Decomposition (roll_effective_spread.py)
3. Dynamic Beta-Neutral Portfolio Hedger (dynamic_beta_hedger.py)
4. Shannon Entropy & Dempster-Shafer Signal Fusion (entropy_signal_combiner.py)
5. Rollup Nonce-Ahead Speed Accelerator (nonce_ahead_accelerator.py)
"""

from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from quant_engines.almgren_chriss_execution import AlmgrenChrissExecutionEngine
from quant_engines.roll_effective_spread import RollEffectiveSpreadEngine
from quant_engines.dynamic_beta_hedger import DynamicBetaHedger
from quant_engines.entropy_signal_combiner import EntropySignalCombiner, AlphaSignalInput
from quant_engines.nonce_ahead_accelerator import RollupNonceAheadAccelerator


def test_almgren_chriss_optimal_schedule():
    engine = AlmgrenChrissExecutionEngine()
    sched = engine.calculate_optimal_schedule(
        symbol="SOL",
        side="BUY",
        total_usd=150.0,
        volatility_sigma=0.025,
        total_duration_seconds=10.0,
        num_steps=5,
    )
    assert sched.num_steps == 5
    assert len(sched.steps) == 5
    assert sum(s.trade_chunk_usd for s in sched.steps) == pytest.approx(150.0, 0.01)
    assert sched.expected_shortfall_cost_bps > 0.0


def test_roll_effective_spread_decomposition():
    engine = RollEffectiveSpreadEngine()

    # Feed alternating bid/ask bounce prices
    base = 200.0
    for i in range(10):
        px = base + (0.10 if i % 2 == 0 else -0.10)
        engine.push_mid_price("SOL", px)

    metrics = engine.compute_effective_spread("SOL", current_mid=200.0, current_quoted_spread_bps=10.0)
    assert metrics.roll_effective_spread_bps > 0.0
    assert metrics.quoted_spread_bps == 10.0
    assert metrics.adverse_selection_cost_bps > 0.0


def test_dynamic_beta_hedger():
    hedger = DynamicBetaHedger()

    # Record 10 pairs: SOL moves 1.6x as much as BTC
    for i in range(10):
        hedger.update_returns("SOL", return_asset_bps=(10.0 + i) * 1.6, return_btc_bps=10.0 + i)

    plan = hedger.construct_beta_hedge("SOL", side="LONG", notional_usd=100.0, benchmark="BTC")
    assert plan.recommended_hedge_side == "SHORT"
    assert plan.recommended_hedge_usd > 100.0  # Beta > 1.0 -> hedge notional is higher
    assert plan.net_portfolio_beta == 0.00


def test_entropy_signal_combiner_consensus():
    combiner = EntropySignalCombiner(min_conviction_threshold=75.0)

    # 4 models all agree on BUY: TreeNews (95%), OFI (88%), Hawkes (80%), Binance Lead (90%)
    signals = [
        AlphaSignalInput(source_name="TreeNews", direction="BUY", confidence_pct=95.0, weight=2.0),
        AlphaSignalInput(source_name="OFI", direction="BUY", confidence_pct=88.0, weight=1.5),
        AlphaSignalInput(source_name="Hawkes", direction="BUY", confidence_pct=80.0, weight=1.0),
        AlphaSignalInput(source_name="BinanceLead", direction="BUY", confidence_pct=90.0, weight=1.5),
    ]

    fused = combiner.fuse_signals("BTC", signals)
    assert fused.master_direction == "BUY"
    assert fused.consensus_conviction_score > 85.0
    assert fused.is_actionable is True
    assert fused.contributing_signals_count == 4


def test_rollup_nonce_ahead_accelerator():
    accel = RollupNonceAheadAccelerator(account_index=737649, api_key_index=5, pool_size=5)

    # Acquire pre-allocated nonce in < 0.01ms
    env = accel.acquire_preallocated_nonce()
    assert env.nonce > 1000
    assert env.account_index == 737649
    assert env.is_reserved is True

    # Test emergency fee bump replacement
    res = accel.accelerate_replacement(nonce=env.nonce, fee_bump_pct=30.0)
    assert res.original_nonce == env.nonce
    assert res.bumped_fee_multiplier == 1.30
    assert res.status == "ACCELERATED"
