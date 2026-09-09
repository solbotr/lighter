#!/usr/bin/env python3
"""
Unit Tests for Phase 23, 24 & 25 Quant Engines (test_institutional_frontier_v18.py)
==================================================================================
1. Two-Scale Realized Volatility Subsampler (microstructure_noise_subsampler.py)
2. Cross-Orderbook Transfer Entropy Flow (cross_orderbook_entropy_flow.py)
3. Cox-Ingersoll-Ross Stochastic Spread Intensity (stochastic_spread_intensity.py)
4. MEV Sandwich Decoy Emitter & Adversary Poisoner (mev_sandwich_decoy_emitter.py)
5. Cross-Market Liquidity Optimal Transport (cross_market_liquidity_transport.py)
6. Black-Litterman Bayesian News Portfolio (black_litterman_news_bayesian.py)
7. Intraday Seasonality Profile & Diurnal Normalizer (intraday_seasonality_profile.py)
8. Continuous Fractional Kelly Compounder (dynamic_kelly_fractional_compounder.py)
9. Stochastic Inventory Barrier Exit (stochastic_inventory_barrier_exit.py)
10. Starknet ZK-Rollup Mempool Arb Frontrunner (zkrollup_mempool_arb_frontrunner.py)
11. Master Institutional Quant Nexus (master_institutional_quant_nexus.py)
"""

from __future__ import annotations

import os
import sys
import time
import math
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from quant_engines.microstructure_noise_subsampler import MicrostructureNoiseSubsampler
from quant_engines.cross_orderbook_entropy_flow import CrossOrderbookEntropyFlowEngine
from quant_engines.stochastic_spread_intensity import StochasticSpreadIntensityEngine
from quant_engines.mev_sandwich_decoy_emitter import MEVSandwichDecoyEmitter
from quant_engines.cross_market_liquidity_transport import CrossMarketLiquidityTransportEngine
from quant_engines.black_litterman_news_bayesian import BlackLittermanNewsBayesianEngine
from intraday_seasonality_profile import IntradaySeasonalityProfileEngine
from quant_engines.dynamic_kelly_fractional_compounder import DynamicKellyFractionalCompounder
from quant_engines.stochastic_inventory_barrier_exit import StochasticInventoryBarrierExitEngine
from quant_engines.zkrollup_mempool_arb_frontrunner import ZkRollupMempoolArbFrontrunner, PendingRollupTx
from quant_engines.master_institutional_quant_nexus import MasterInstitutionalQuantNexus


def test_tsrv_noise_subsampler():
    filter_tsrv = MicrostructureNoiseSubsampler(subsample_k=5)
    for i in range(25):
        filter_tsrv.push_tick_price("BTC", 95000.0 + (i % 2) * 5.0)  # Microstructure bounce
    res = filter_tsrv.compute_tsrv("BTC")
    assert res.symbol == "BTC"
    assert res.pure_tsrv_vol_pct > 0.0


def test_cross_orderbook_entropy_flow():
    engine = CrossOrderbookEntropyFlowEngine()
    for _ in range(15):
        engine.push_tick_states("SOL", leader_delta=0.10, follower_delta=0.08)
    res = engine.compute_transfer_entropy("SOL")
    assert res.transfer_entropy_bits > 0.0
    assert res.is_frontrun_actionable is True


def test_cir_stochastic_spread():
    engine = StochasticSpreadIntensityEngine()
    res = engine.calibrate_spread_cir("SOL", current_spread_bps=12.5, equilibrium_spread_theta_bps=4.0)
    assert res.symbol == "SOL"
    assert res.is_feller_strictly_positive is True
    assert res.spread_z_score >= 1.80
    assert res.is_spread_mean_reversion_tradeable is True


def test_mev_decoy_emitter():
    emitter = MEVSandwichDecoyEmitter()
    shield = emitter.generate_decoy_shield("SOL", real_side="BUY", real_size_usd=100.0, mid_price=200.0)
    assert shield.active_decoys_count >= 2
    assert shield.adversary_poison_score > 90.0
    assert shield.is_protected is True


def test_wasserstein_liquidity_transport():
    engine = CrossMarketLiquidityTransportEngine()
    src_profile = [10000.0, 25000.0, 50000.0]
    tgt_profile = [12000.0, 24000.0, 48000.0]
    res = engine.compute_wasserstein_distance("HYPERLIQUID", "ZKLIGHTER", "SOL", src_profile, tgt_profile, 200.0)
    assert res.symbol == "SOL"
    assert res.wasserstein_distance_usd >= 0.0


def test_black_litterman_bayesian():
    engine = BlackLittermanNewsBayesianEngine()
    eq_w = {"BTC": 0.40, "ETH": 0.30, "SOL": 0.30}
    views = {"SOL": (6.5, 95.0)}  # Breaking bullish news on SOL
    plan = engine.blend_news_views(total_capital_usd=740.86, equilibrium_weights=eq_w, news_views=views)
    assert plan.news_views_count == 1
    # SOL weight should expand
    sol_alloc = next(a for a in plan.allocations if a.symbol == "SOL")
    assert sol_alloc.bl_posterior_weight_pct > 30.0


def test_intraday_seasonality_profile():
    engine = IntradaySeasonalityProfileEngine()
    m_ny = engine.evaluate_current_seasonality(utc_hour=14)  # NY open
    assert m_ny.session_name == "US_NY_OPEN_PEAK"
    assert m_ny.is_peak_liquidity_window is True
    assert m_ny.diurnal_volatility_multiplier > 1.50


def test_dynamic_fractional_kelly():
    compounder = DynamicKellyFractionalCompounder()
    res = compounder.compute_optimal_size("SOL", total_portfolio_usd=740.86, win_probability_p=0.72, payoff_ratio_b=2.50)
    assert res.full_kelly_fraction_pct > 0.0
    assert res.recommended_position_usd > 50.0
    assert res.is_safe_allocation is True


def test_stochastic_inventory_barrier_exit():
    engine = StochasticInventoryBarrierExitEngine()
    res = engine.evaluate_inventory_barrier(
        "SOL",
        inventory_qty=2.5,
        current_pnl_bps=15.0,
        upper_barrier_bps=20.0,
        lower_barrier_bps=-40.0,
    )
    assert res.symbol == "SOL"
    assert res.prob_hit_profit_barrier_pct > 50.0
    assert res.recommended_action in ("HOLD_RUNNER", "PARTIAL_TRIM")


def test_zkrollup_mempool_arb():
    frontrunner = ZkRollupMempoolArbFrontrunner()
    pending = [
        PendingRollupTx("0x1", "SOL", "BUY", 15000.0, "WHALE_SWAP"),
        PendingRollupTx("0x2", "SOL", "BUY", 20000.0, "LIQUIDATION"),
    ]
    opp = frontrunner.evaluate_pending_batch("SOL", pending, current_book_depth_usd=40000.0)
    assert opp is not None
    assert opp.target_action == "BUY"
    assert opp.is_immediate_fire is True


def test_master_quant_nexus():
    nexus = MasterInstitutionalQuantNexus(portfolio_usd=740.86)
    telemetry = nexus.get_system_telemetry()
    assert telemetry.active_quant_engines_count == 0
    assert telemetry.nexus_state == "UNKNOWN"
    assert telemetry.daily_sharpe_ratio == 0.0
    assert telemetry.total_volume_farmed_usd == 0.0
    assert telemetry.total_portfolio_usd == 740.86
    assert telemetry.total_pipeline_latency_us == 0.0


def test_master_quant_nexus_registry_and_overrides():
    nexus = MasterInstitutionalQuantNexus(
        portfolio_usd=100.0,
        engine_registry=["a", "b", "c"],
    )
    configured = nexus.get_system_telemetry()
    assert configured.active_quant_engines_count == 3
    assert configured.nexus_state == "CONFIGURED"

    displayed = nexus.get_system_telemetry(
        active_engines=8,
        health="ALL_SYSTEMS_OPTIMAL",
        daily_sharpe_ratio=1.25,
        total_volume_farmed_usd=50.0,
    )
    assert displayed.active_quant_engines_count == 8
    assert displayed.nexus_state == "ALL_SYSTEMS_OPTIMAL"
    assert displayed.daily_sharpe_ratio == 1.25
    assert displayed.total_volume_farmed_usd == 50.0
    assert displayed.total_portfolio_usd == 100.0
