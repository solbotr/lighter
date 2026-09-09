#!/usr/bin/env python3
"""
Unit Tests for Phase 21 Quant Engines (test_institutional_frontier_v16.py)
===========================================================================
1. Sub-50μs Shared Memory Ring Buffer Pipeline (native_fast_ring_buffer.py)
2. Cross-Asset Graph Diffusion Alpha Network (graph_diffusion_alpha.py)
3. Heston Stochastic Volatility Surface Calibrator (heston_volatility_surface.py)
4. Synthetic Dark Liquidity Aggregator & Iceberg Router (synthetic_dark_aggregator.py)
5. On-Chain Proof-of-Solvency & Disaster Recovery Vault (disaster_recovery_vault.py)
"""

from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from quant_engines.native_fast_ring_buffer import NativeFastRingBuffer
from quant_engines.graph_diffusion_alpha import CrossAssetGraphDiffusionNetwork
from quant_engines.heston_volatility_surface import HestonVolatilitySurfaceCalibrator
from quant_engines.synthetic_dark_aggregator import SyntheticDarkLiquidityAggregator
from quant_engines.disaster_recovery_vault import DisasterRecoveryVault


def test_native_fast_ring_buffer():
    rb = NativeFastRingBuffer(capacity=64)

    # 1. Write 20 message slots in < 0.1ms
    for i in range(20):
        seq = rb.write_slot(payload_type="TICK", symbol="SOL", price=200.0 + i, size=1.0)
        assert seq == i + 1

    # 2. Read 20 message slots
    for i in range(20):
        slot = rb.read_next_slot()
        assert slot is not None
        assert slot.symbol == "SOL"
        assert slot.sequence_id == i + 1

    metrics = rb.get_metrics()
    assert metrics.total_written == 20
    assert metrics.total_read == 20
    assert metrics.average_hop_latency_us <= 50.0  # <= 50 microseconds


def test_graph_diffusion_alpha_network():
    network = CrossAssetGraphDiffusionNetwork(diffusion_alpha=0.35, min_diffusion_threshold=60.0)

    # Breaking catalyst on NEAR (AI Cluster) -> Should propagate to RENDER, FET, TAO
    res = network.propagate_catalyst(primary_asset="NEAR", direction="BUY", catalyst_conviction_score=95.0)

    assert res.primary_catalyst_asset == "NEAR"
    assert res.sentiment_direction == "BUY"
    assert res.diffused_assets_count >= 2

    # Verify RENDER and FET are in top diffused alphas
    symbols = [a.symbol for a in res.top_propagated_alphas]
    assert "RENDER" in symbols
    assert "FET" in symbols


def test_heston_volatility_surface_calibrator():
    calibrator = HestonVolatilitySurfaceCalibrator(default_kappa=2.50, default_vol_of_vol=0.65)

    params = calibrator.calibrate_surface(
        symbol="BTC",
        spot_price=95000.0,
        current_atm_vol_pct=52.0,
        historical_mean_vol_pct=48.0,
        put_call_skew_vols=2.5,
    )

    assert params.symbol == "BTC"
    assert params.spot_price == 95000.0
    assert params.mean_reversion_kappa == 2.50
    assert params.leverage_correlation_rho < 0.0  # Downside skew
    assert params.is_feller_condition_satisfied is True
    assert params.tail_risk_probability_3sigma_pct > 0.0


def test_synthetic_dark_liquidity_aggregator():
    aggregator = SyntheticDarkLiquidityAggregator(min_slice_usd=15.0, max_slice_usd=40.0)

    # Route $120 order across zkLighter and Hyperliquid
    plan = aggregator.construct_dark_route(symbol="SOL", side="BUY", total_usd=120.0, mid_price=200.0)

    assert plan.symbol == "SOL"
    assert plan.side == "BUY"
    assert plan.num_slices >= 3
    assert sum(s.slice_size_usd for s in plan.slices) == pytest.approx(120.0, 0.01)
    assert plan.mev_protection_score > 90.0


def test_disaster_recovery_vault():
    vault = DisasterRecoveryVault(max_heartbeat_timeout_sec=2.0)

    # 1. Normal state (fresh pings)
    vault.update_heartbeat("ZKLIGHTER", latency_ms=12.0)
    vault.update_heartbeat("HYPERLIQUID", latency_ms=18.0)
    s1 = vault.evaluate_system_health()
    assert s1.is_emergency_failover_active is False

    # 2. Simulate zkLighter sequencer crash (simulate 5s blackout)
    vault.heartbeats["ZKLIGHTER"].last_ping_timestamp = time.time() - 10.0
    s2 = vault.evaluate_system_health()
    assert s2.is_emergency_failover_active is True
    assert "ZKLIGHTER" in s2.compromised_venues
    assert s2.active_backup_venue == "HYPERLIQUID"
    assert s2.cancelled_orders_count > 0
