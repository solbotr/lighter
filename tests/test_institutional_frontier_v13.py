#!/usr/bin/env python3
"""
Unit Tests for Phase 18 Quant Engines (test_institutional_frontier_v13.py)
===========================================================================
1. Kyle-Obizhaeva Market Microstructure Invariance (microstructure_invariance.py)
2. Garman-Klass Realized Volatility Estimator (garman_klass_volatility.py)
3. Continuous Inventory Convexity Skew (inventory_convexity_skew.py)
4. Merton Jump-Diffusion Funding Spike Predictor (funding_jump_diffusion.py)
5. L2 Proof Verification & State Drift Detector (l2_proof_drift_detector.py)
"""

from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from microstructure_invariance import MicrostructureInvarianceEngine
from garman_klass_volatility import GarmanKlassVolatilityEstimator, OHLCBar
from inventory_convexity_skew import InventoryConvexitySkewEngine
from funding_jump_diffusion import FundingJumpDiffusionPredictor
from l2_proof_drift_detector import L2ProofDriftDetector


def test_microstructure_invariance():
    engine = MicrostructureInvarianceEngine(target_trade_risk_fraction=0.05)
    metrics = engine.compute_invariance_parameters("BTC", price=95000.0, volume_24h_usd=2500000000.0, volatility_sigma=0.035)

    assert metrics.invariant_liquidity_L > 100000.0
    assert metrics.invariant_order_size_usd > 0.0
    assert metrics.recommended_trade_chunk_usd >= 10.0
    assert metrics.optimal_execution_horizon_sec > 0.0


def test_garman_klass_realized_volatility():
    estimator = GarmanKlassVolatilityEstimator(window_bars=10)

    # Feed 10 OHLC bars with high intra-candle range
    base = 200.0
    for i in range(10):
        estimator.push_bar(
            "SOL",
            OHLCBar(open=base, high=base + 4.0, low=base - 4.0, close=base + 1.0),
        )

    state = estimator.compute_volatility("SOL")
    assert state.garman_klass_volatility_pct > 50.0
    assert state.spread_multiplier >= 1.0


def test_inventory_convexity_skew():
    engine = InventoryConvexitySkewEngine(max_position_limit_usd=200.0)

    # 1. Normal balanced inventory ($0)
    s1 = engine.compute_convex_quote_skew("ETH", current_inventory_usd=0.0)
    assert s1.inventory_utilization_pct == 0.0
    assert s1.is_emergency_offload_active is False

    # 2. Extreme Long inventory ($180 / $200 = 90% utilization) -> Emergency offload
    s2 = engine.compute_convex_quote_skew("ETH", current_inventory_usd=180.0)
    assert s2.inventory_utilization_pct == 90.0
    assert s2.is_emergency_offload_active is True
    assert s2.convex_penalty_bps > 0.0


def test_funding_jump_diffusion_prediction():
    predictor = FundingJumpDiffusionPredictor()

    # Ingest 10 hourly samples with sudden rate jumps
    rates = [0.0001, 0.0001, 0.00012, 0.00015, 0.00025, 0.00045, 0.00075]
    for r in rates:
        predictor.push_funding_sample("SOL", hourly_rate=r)

    forecast = predictor.forecast_next_funding_rate("SOL")
    assert forecast.predicted_funding_rate_hourly > 0.0001
    assert forecast.annualized_yield_apr_pct > 20.0


def test_l2_proof_drift_detector():
    detector = L2ProofDriftDetector(account_index=737649, max_drift_tolerance_usd=0.05)

    # 1. Register proof batch
    snap = detector.register_rollup_proof_batch(batch_index=50001, state_root_hex="0xdeadbeef1234")
    assert snap.batch_index == 50001

    # 2. Verify matching balance ($730.09)
    res_sync = detector.verify_account_state(local_balance_usd=730.09, onchain_reported_balance_usd=730.09)
    assert res_sync.is_state_synchronized is True
    assert res_sync.circuit_breaker_active is False

    # 3. Verify balance drift ($730.09 local vs $700.00 onchain) -> Triggers Circuit Breaker
    res_drift = detector.verify_account_state(local_balance_usd=730.09, onchain_reported_balance_usd=700.00)
    assert res_drift.is_state_synchronized is False
    assert res_drift.circuit_breaker_active is True
    assert res_drift.discrepancy_usd == pytest.approx(30.09, 0.01)
