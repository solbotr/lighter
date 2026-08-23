#!/usr/bin/env python3
"""
Unit Tests for Phase 15 Quant Modules (test_institutional_frontier_v10.py)
===========================================================================
1. Asymmetric Avellaneda-Stoikov Inventory Quoter (asymmetric_quoting_engine.py)
2. Microstructure HMM Regime Switcher (microstructure_hmm.py)
3. Catalyst Anchored-VWAP & Volume Profile (anchored_vwap_profile.py)
4. Cross-Exchange Synthetic Basis Carry (synthetic_basis_carry.py)
5. Rollup Sequencer Batch Window Arbitrageur (sequencer_lag_detector.py)
"""

from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from asymmetric_quoting_engine import AsymmetricQuotingEngine
from microstructure_hmm import MicrostructureHMMClassifier, MarketRegimeState
from anchored_vwap_profile import AnchoredVWAPProfileEngine
from synthetic_basis_carry import SyntheticBasisCarryOptimizer
from sequencer_lag_detector import RollupSequencerLagDetector


def test_asymmetric_quoting_inventory_skew():
    engine = AsymmetricQuotingEngine()

    # 1. Balanced inventory q = 0
    q_neutral = engine.compute_asymmetric_quotes("ETH", mid_price=2000.0, volatility_sigma=0.02, current_inventory=0.0)
    assert q_neutral.reservation_price == 2000.0
    assert q_neutral.optimal_bid < 2000.0
    assert q_neutral.optimal_ask > 2000.0

    # 2. Heavy Long inventory q = +5.0 ETH -> Reservation price drops to incentivize selling
    q_long = engine.compute_asymmetric_quotes("ETH", mid_price=2000.0, volatility_sigma=0.02, current_inventory=5.0)
    assert q_long.reservation_price < 2000.0
    assert q_long.optimal_ask < q_neutral.optimal_ask  # Asks are pushed tighter to dump inventory!


def test_microstructure_hmm_regime_switch():
    hmm = MicrostructureHMMClassifier()

    # 1. Low volatility mean reverting
    res1 = hmm.update_tick_features("SOL", price_return_bps=1.0, ofi_score=2.0, vpin_score=0.20)
    assert res1.current_state == MarketRegimeState.MEAN_REVERTING
    assert res1.recommended_strategy == "MARKET_MAKING"

    # 2. Sudden high-momentum breakout
    res2 = hmm.update_tick_features("SOL", price_return_bps=18.0, ofi_score=35.0, vpin_score=0.40)
    assert res2.current_state == MarketRegimeState.TREND_BREAKOUT
    assert res2.recommended_strategy == "DIRECTIONAL_SNIPER"

    # 3. Toxic dump cascade
    res3 = hmm.update_tick_features("SOL", price_return_bps=-45.0, ofi_score=-40.0, vpin_score=0.78)
    assert res3.current_state == MarketRegimeState.TOXIC_CASCADE
    assert res3.recommended_strategy == "LIQUIDATION_HUNTER"


def test_anchored_vwap_and_volume_profile():
    engine = AnchoredVWAPProfileEngine()
    t0 = time.time()
    engine.set_catalyst_anchor("BTC", anchor_timestamp=t0)

    # Push ticks: Heavy volume concentrated at 95,000, then surges to 96,000 with lighter volume
    engine.push_tick("BTC", price=95000.0, volume_usd=500000.0, timestamp=t0)
    engine.push_tick("BTC", price=95500.0, volume_usd=200000.0, timestamp=t0 + 1)
    engine.push_tick("BTC", price=96000.0, volume_usd=50000.0, timestamp=t0 + 2)

    profile = engine.compute_anchored_profile("BTC", current_price=96000.0, direction="BUY")
    assert profile.total_anchored_volume_usd == 750000.0
    assert profile.anchored_vwap < 96000.0
    assert profile.point_of_control_price == pytest.approx(95000.0, rel=1e-3)


def test_synthetic_basis_carry_optimizer():
    optimizer = SyntheticBasisCarryOptimizer(min_actionable_apr_pct=15.0)

    # Lighter ETH funding = 0.002% / hr (~17.5% APR)
    optimizer.update_yield_rate("ETH", "ZKLIGHTER", hourly_funding_rate=0.00002, spot_lending_apr_pct=3.0)
    # Hyperliquid SOL funding = 0.006% / hr (~52.5% APR)
    optimizer.update_yield_rate("SOL", "HYPERLIQUID", hourly_funding_rate=0.00006, spot_lending_apr_pct=4.0)

    plan = optimizer.optimize_carry_portfolio(available_capital_usd=250.0)
    assert plan is not None
    assert plan.target_symbol == "SOL"
    assert plan.target_venue == "HYPERLIQUID"
    assert plan.net_carry_apr_pct > 50.0
    assert plan.expected_annual_yield_usd > 100.0


def test_rollup_sequencer_lag_detector():
    detector = RollupSequencerLagDetector(target_window_start_ms=20.0)

    # Register block
    detector.register_sequencer_block(block_number=1000100, tx_count=45)
    status = detector.get_inclusion_window_status()

    assert status.current_block == 1000100
    assert status.estimated_priority_rank in (1, 2)
