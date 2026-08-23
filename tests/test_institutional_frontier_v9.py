#!/usr/bin/env python3
"""
Unit Tests for Phase 14 Advanced Quant Engines (test_institutional_frontier_v9.py)
==================================================================================
1. Binance L3 Pre-Emptive Repricing Arbitrage (binance_lead_repricer.py)
2. Hawkes Process Order Clustering & Intensity (hawkes_order_intensity.py)
3. VPIN Toxic Flow Detector (vpin_toxic_flow.py)
4. Deribit Options IV & Gamma Skew Modeler (iv_surface_skew.py)
5. Pipelined Sub-1ms Atomic Order State Machine (pipelined_state_machine.py)
"""

from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from binance_lead_repricer import BinanceLeadRepricingEngine
from hawkes_order_intensity import HawkesOrderIntensityEngine
from vpin_toxic_flow import VPINToxicFlowDetector
from iv_surface_skew import IVSurfaceSkewModeler
from pipelined_state_machine import PipelinedOrderStateMachine, OrderState


def test_binance_lead_repricing_arbitrage():
    engine = BinanceLeadRepricingEngine(min_dislocation_bps=10.0)

    # Ingest Binance trade: BTC surges to 95,200
    engine.on_binance_trade_tick("BTC", price=95200.0, volume_usd=100000.0, side="BUY")

    # zkLighter still has stale resting ask at 95,000 (dislocation ~21 bps)
    opp = engine.evaluate_stale_quotes("BTC", lighter_best_bid=94950.0, lighter_best_ask=95000.0, available_capital_usd=200.0)
    assert opp is not None
    assert opp.direction == "TAKE_ASK_LONG"
    assert opp.dislocation_bps > 15.0
    assert opp.estimated_profit_usd > 0.0


def test_hawkes_order_clustering_and_intensity():
    engine = HawkesOrderIntensityEngine(baseline_mu=0.5, alpha=1.2, beta=1.8)

    # Register 6 rapid buy trades within 2 seconds
    t0 = time.time()
    for i in range(6):
        state = engine.register_trade("ETH", volume_usd=50000.0, side="BUY", timestamp=t0 + (i * 0.2))

    assert state.is_cascade_active is True
    assert state.current_intensity_lambda > 1.5
    assert state.sizing_multiplier > 1.0
    assert state.dominant_side == "BUY"


def test_vpin_toxic_flow_detection():
    detector = VPINToxicFlowDetector(bucket_size_usd=10000.0, num_buckets=5, toxicity_threshold=0.60)

    # Feed heavily one-sided toxic sell volume
    for _ in range(8):
        state = detector.push_trade("SOL", volume_usd=10000.0, side="SELL")

    assert state.current_vpin_score > 0.80
    assert state.is_toxic_flow_detected is True
    assert state.recommended_action == "PAUSE_MAKER"


def test_iv_surface_skew_and_sentiment():
    modeler = IVSurfaceSkewModeler(high_skew_threshold_vols=5.0)

    # Deribit BTC options: Put 25d IV = 62%, Call 25d IV = 54% -> Skew = +8.0 vols (extreme hedging)
    metrics = modeler.update_surface_quotes(
        symbol="BTC",
        atm_iv=55.0,
        put_25d_iv=62.0,
        call_25d_iv=54.0,
        front_month_iv=56.0,
        back_month_iv=52.0,
    )

    assert metrics.skew_25d_vol == 8.0
    assert metrics.sentiment_regime == "EXTREME_BEAR_HEDGING"
    assert metrics.tighten_long_stops is True


def test_pipelined_order_state_machine():
    sm = PipelinedOrderStateMachine()
    ord_rec = sm.create_order("BTC", "BUY", price=95000.0, amount_usd=150.0, nonce=101)
    assert ord_rec.current_state == OrderState.CREATED

    assert sm.mark_signed(ord_rec.client_order_id) is True
    assert ord_rec.current_state == OrderState.SIGNED

    assert sm.mark_submitted(ord_rec.client_order_id) is True
    assert ord_rec.current_state == OrderState.SUBMITTED

    assert sm.mark_filled(ord_rec.client_order_id, tx_hash="0xdeadbeef") is True
    assert ord_rec.current_state == OrderState.FILLED
    assert ord_rec.client_order_id in sm.completed_orders
    assert len(ord_rec.transitions) == 3
