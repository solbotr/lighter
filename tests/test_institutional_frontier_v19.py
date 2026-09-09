#!/usr/bin/env python3
"""
Unit Test Suite for Phase 26 Quant Upgrades (tests/test_institutional_frontier_v19.py)
=====================================================================================
Validates:
1. MultiPositionConcurrencyEngine (concurrency slots, sector guards, Kelly margin sizing)
2. AsymmetricTPMaximizer (3-tier scale-out profit ladder, breakeven lock, trailing runner)
3. MomentumPyramidScaler (volume surge pyramid, risk-free addition)
"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pytest

from quant_engines.multi_position_concurrency_engine import MultiPositionConcurrencyEngine
from quant_engines.asymmetric_tp_maximizer import AsymmetricTPMaximizer
from quant_engines.momentum_pyramid_scaler import MomentumPyramidScaler


def test_multi_position_concurrency_slots():
    engine = MultiPositionConcurrencyEngine(
        max_concurrent_positions=5,
        max_total_margin_pct=85.0,
        max_sector_positions=2,
    )
    total_port = 1000.0

    # 1. First entry (BTC)
    d1 = engine.evaluate_new_entry("BTC", catalyst_conviction_score=98.0, total_portfolio_usd=total_port)
    assert d1.is_allowed is True
    assert d1.recommended_margin_usd > 100.0
    engine.register_entry("pos-btc", "BTC", "LONG", d1.recommended_margin_usd, total_port)

    # 2. Second entry in same sector (ETH - CORE_L1)
    d2 = engine.evaluate_new_entry("ETH", catalyst_conviction_score=90.0, total_portfolio_usd=total_port)
    assert d2.is_allowed is True
    engine.register_entry("pos-eth", "ETH", "LONG", d2.recommended_margin_usd, total_port)

    # 3. Third entry in different sector (SOL - SOLANA)
    d3 = engine.evaluate_new_entry("SOL", catalyst_conviction_score=85.0, total_portfolio_usd=total_port)
    assert d3.is_allowed is True
    engine.register_entry("pos-sol", "SOL", "LONG", d3.recommended_margin_usd, total_port)

    # 4. Duplicate entry blocked
    d_dup = engine.evaluate_new_entry("BTC", catalyst_conviction_score=99.0, total_portfolio_usd=total_port)
    assert d_dup.is_allowed is False
    assert "already open" in d_dup.rejection_reason

    # 5. Close BTC and verify slot freed
    engine.register_close("BTC")
    assert "BTC" not in engine.active_slots


def test_asymmetric_tp_maximizer_ladder():
    maximizer = AsymmetricTPMaximizer(tp1_gain_pct=2.5, tp2_gain_pct=5.0, tp3_target_pct=12.0)
    entry_px = 100.0

    plan = maximizer.create_profit_plan("pos-1", "SOL", entry_price=entry_px, is_long=True)
    assert plan.current_stage == "STAGE_ENTRY"

    # Price moves to +2.6% -> TP1 triggered, SL moved to BE (+0.1%)
    plan, step = maximizer.evaluate_price_update("pos-1", current_price=102.60, is_long=True)
    assert step is not None
    assert step.step_level == 1
    assert plan.current_stage == "STAGE_BE_LOCKED"
    assert plan.active_trailing_stop_pct >= 0.1

    # Price moves to +5.2% -> TP2 triggered, floor raised to +2.5%
    plan, step = maximizer.evaluate_price_update("pos-1", current_price=105.20, is_long=True)
    assert step is not None
    assert step.step_level == 2
    assert plan.current_stage == "STAGE_TP2_LOCKED"
    assert plan.active_trailing_stop_pct >= 2.5

    # Price extends to +15.0% -> Runner active with dynamic trailing stop
    plan, step = maximizer.evaluate_price_update("pos-1", current_price=115.00, is_long=True, current_atr_pct=1.0)
    assert plan.current_stage == "STAGE_RUNNER"
    assert plan.active_trailing_stop_pct > 5.0


def test_momentum_pyramid_scaler_execution():
    scaler = MomentumPyramidScaler(min_profit_to_pyramid_pct=1.5, max_pyramid_adds=2, add_size_ratio=0.25)

    # 1. In profit but not BE locked -> No add
    sig_no_be = scaler.evaluate_pyramid_opportunity(
        "pos-1", "ETH", initial_size_usd=200.0, current_profit_pct=2.0, current_volume_multiplier=3.0, is_breakeven_locked=False, current_price=2040.0
    )
    assert sig_no_be is None

    # 2. In profit, BE locked, volume surge 3.2x -> Triggers Pyramid Add #1
    sig1 = scaler.evaluate_pyramid_opportunity(
        "pos-1", "ETH", initial_size_usd=200.0, current_profit_pct=2.5, current_volume_multiplier=3.2, is_breakeven_locked=True, current_price=2050.0
    )
    assert sig1 is not None
    assert sig1.pyramid_level == 1
    assert sig1.additional_size_usd == 50.0  # 25% of $200
    assert sig1.is_risk_free_pyramid is True

    # 3. Triggers Pyramid Add #2 on higher profit
    sig2 = scaler.evaluate_pyramid_opportunity(
        "pos-1", "ETH", initial_size_usd=200.0, current_profit_pct=4.5, current_volume_multiplier=2.8, is_breakeven_locked=True, current_price=2090.0
    )
    assert sig2 is not None
    assert sig2.pyramid_level == 2

    # 4. Max adds reached (2) -> Next check returns None
    sig3 = scaler.evaluate_pyramid_opportunity(
        "pos-1", "ETH", initial_size_usd=200.0, current_profit_pct=6.0, current_volume_multiplier=3.5, is_breakeven_locked=True, current_price=2120.0
    )
    assert sig3 is None
