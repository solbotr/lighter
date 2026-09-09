#!/usr/bin/env python3
"""
Unit Tests for Phase 22 Quant Engines (test_institutional_frontier_v17.py)
===========================================================================
1. Second-Order Quadratic OFI Curvature (quadratic_ofi_curvature.py)
2. Markov Jump Copula & Tail Dependence (markov_jump_copula.py)
3. Orderbook Liquidity Vacuum Magnet (liquidity_vacuum_absorber.py)
4. Exponential Alpha Decay Predictor (alpha_decay_predictor.py)
5. Starknet ZK-Rollup Priority Gas Auction Sizer (rollup_pga_sizer.py)
"""

from __future__ import annotations

import os
import sys
import time
import math
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from quant_engines.quadratic_ofi_curvature import QuadraticOFICurvatureEngine
from quant_engines.markov_jump_copula import MarkovJumpCopulaEngine
from quant_engines.liquidity_vacuum_absorber import LiquidityVacuumAbsorberEngine, OrderbookDepthLevel
from quant_engines.alpha_decay_predictor import AlphaDecayPredictorEngine
from quant_engines.rollup_pga_sizer import RollupPGASizerEngine


def test_quadratic_ofi_curvature():
    engine = QuadraticOFICurvatureEngine()

    t0 = time.time()
    # Ingest accelerating OFI (+10 -> +25 -> +50)
    engine.push_order_flow_imbalance("BTC", linear_ofi=10.0, timestamp=t0)
    engine.push_order_flow_imbalance("BTC", linear_ofi=25.0, timestamp=t0 + 0.1)
    res = engine.push_order_flow_imbalance("BTC", linear_ofi=50.0, timestamp=t0 + 0.2)

    assert res.symbol == "BTC"
    assert res.linear_ofi == 50.0
    assert res.acceleration_velocity > 0.0
    assert res.predicted_price_impact_bps > 0.0
    assert res.direction == "BULLISH_ACCELERATION"


def test_markov_jump_copula():
    engine = MarkovJumpCopulaEngine()

    # Record 15 highly correlated returns
    for i in range(15):
        engine.push_paired_returns("BTC", "SOL", r1_bps=10.0 + i, r2_bps=12.0 + i)

    res = engine.estimate_tail_dependence("BTC", "SOL")
    assert res.pair_name == "BTC_SOL"
    assert res.lower_tail_dependence_lambda_l > 0.0
    assert res.upper_tail_dependence_lambda_u > 0.0
    assert res.is_decoupled is False


def test_liquidity_vacuum_absorber():
    engine = LiquidityVacuumAbsorberEngine(vacuum_threshold_pct=20.0, min_vacuum_span_bps=10.0)

    # 10 ask levels: Levels 2..5 are thin air pockets ($5,000 depth vs $80,000 normal), Level 6 is massive shelf ($150,000)
    levels = [
        OrderbookDepthLevel(price=200.0, depth_usd=80000.0),
        OrderbookDepthLevel(price=200.5, depth_usd=5000.0),  # Thin
        OrderbookDepthLevel(price=201.0, depth_usd=4000.0),  # Thin
        OrderbookDepthLevel(price=201.5, depth_usd=5000.0),  # Thin
        OrderbookDepthLevel(price=202.0, depth_usd=150000.0), # Massive shelf
    ]

    zone = engine.scan_orderbook_for_vacuums("SOL", side="ASK", levels=levels)
    assert zone is not None
    assert zone.side == "ASK_VACUUM"
    assert zone.shelf_target_price == 202.0
    assert zone.vacuum_density_ratio < 0.20
    assert zone.is_actionable is True


def test_alpha_decay_predictor():
    engine = AlphaDecayPredictorEngine()
    t_entry = time.time() - 30.0  # 30 seconds ago

    # Exchange listing announcement (half-life 35s, optimal exit 75s)
    res = engine.compute_decay_horizon("EXCHANGE_LISTING", "SOL", entry_timestamp=t_entry, initial_alpha_bps=80.0)

    assert res.catalyst_type == "EXCHANGE_LISTING"
    assert res.half_life_seconds == 35.0
    assert res.optimal_exit_seconds == 75.0
    assert res.current_decay_pct > 40.0
    assert res.is_exhaustion_reached is False


def test_rollup_pga_sizer():
    sizer = RollupPGASizerEngine(min_tip_gwei=0.05)

    # Ingest 10 competitor tip observations
    tips = [0.08, 0.10, 0.12, 0.15, 0.18, 0.22, 0.25, 0.30, 0.35, 0.40]
    for t in tips:
        sizer.register_competitor_tip(t)

    bid = sizer.compute_optimal_pga_bid(base_fee_gwei=0.15, catalyst_urgency_conviction_pct=95.0)
    assert bid.expected_block_inclusion_rank == 1
    assert bid.recommended_tip_gwei > 0.20
    assert bid.total_effective_fee_gwei > bid.base_fee_gwei
    assert bid.gas_savings_pct > 0.0
