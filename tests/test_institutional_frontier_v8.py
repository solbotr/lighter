#!/usr/bin/env python3
"""
Unit Tests for Phase 13 Core Quant & Microstructure Engines (test_institutional_frontier_v8.py)
==============================================================================================
1. Microsecond Order Flow Imbalance (OFI) Predictor (order_flow_imbalance_engine.py)
2. CEX-DEX Lead-Lag & Triangular Arbitrage (triangular_arbitrage_engine.py)
3. Delta-Neutral Funding Harvester & Basis Vault (delta_neutral_basis_vault.py)
4. Volatility-Envelope Chandelier Trailing Runner (chandelier_trailing_engine.py)
5. Anti-MEV Micro-Iceberg Slicer & Stealth Router (stealth_iceberg_router.py)
"""

from __future__ import annotations

import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from quant_engines.order_flow_imbalance_engine import MicrosecondOFIPredictor
from quant_engines.triangular_arbitrage_engine import TriangularArbitrageEngine
from quant_engines.delta_neutral_basis_vault import DeltaNeutralBasisVault
from chandelier_trailing_engine import ChandelierTrailingEngine, CandleBar
from stealth_iceberg_router import StealthIcebergRouter


def test_order_flow_imbalance_prediction():
    predictor = MicrosecondOFIPredictor(rolling_window_size=10, z_threshold=1.5)

    # Initial snapshot
    p1 = predictor.update_orderbook_top("SOL", bid_price=195.0, bid_size=100.0, ask_price=195.2, ask_size=100.0)
    assert p1.symbol == "SOL"

    # Aggressive bid size increase (buying pressure)
    p2 = predictor.update_orderbook_top("SOL", bid_price=195.1, bid_size=250.0, ask_price=195.2, ask_size=50.0)
    assert p2.current_ofi_score > 0
    assert p2.ask_fill_probability_pct > 50.0


def test_triangular_arbitrage_detection():
    arb = TriangularArbitrageEngine(min_profit_threshold_bps=5.0)
    cycle = arb.evaluate_triangular_cycle(
        base1="SOL",
        base2="ETH",
        quote="USDC",
        px_base1_quote=150.0,
        px_base2_quote=2000.0,
        px_base1_base2=0.0740,
        available_margin_usd=500.0,
    )
    assert cycle is not None
    assert cycle.gross_dislocation_bps > 10.0
    assert cycle.is_actionable is True


def test_delta_neutral_basis_vault():
    vault = DeltaNeutralBasisVault(symbol="SOL", initial_capital_usd=200.0)
    state = vault.allocate_initial_position(spot_price=100.0, perp_price=100.0)
    assert state.net_delta_usd == 0.0

    payout = vault.harvest_funding_payment(funding_rate_8h=0.0004, spot_price=100.0, perp_price=100.0)
    assert payout > 0.0
    assert vault.spot_balance > 1.0


def test_chandelier_trailing_runner_expansion():
    engine = ChandelierTrailingEngine(base_multiplier=2.0, catalyst_expansion_multiplier=3.0)

    # Push 15 historical candles
    for i in range(15):
        px = 100.0 + (i * 0.5)
        engine.push_candle("SOL", CandleBar(open=px - 0.2, high=px + 0.5, low=px - 0.5, close=px))

    # SOL surges from 100 to 115
    state = engine.update_runner_stop(
        symbol="SOL",
        side="LONG",
        entry_price=100.0,
        current_price=115.0,
        is_catalyst_active=True,
    )
    assert state.stop_price > 100.0
    assert state.atr_multiplier == 3.0
    assert not state.is_triggered


@pytest.mark.asyncio
async def test_stealth_iceberg_slicing_and_execution():
    router = StealthIcebergRouter(min_slice_usd=25.0, max_slice_usd=60.0)
    parent = router.slice_parent_order(
        symbol="SOL",
        side="BUY",
        total_usd=150.0,
        reference_price=200.0,
    )

    assert len(parent.slices) >= 3
    assert sum(s.amount_usd for s in parent.slices) == pytest.approx(150.0, 0.01)

    completed = await router.execute_stealth_iceberg(parent)
    assert completed.status == "COMPLETED"
    assert completed.total_filled_usd == pytest.approx(150.0, 0.01)
    assert completed.average_fill_price == pytest.approx(200.0, 0.01)
