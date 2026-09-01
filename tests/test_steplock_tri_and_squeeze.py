import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from parabolic_profit_steplock import calculate_parabolic_steplock
from triangular_arbitrage import TriangularArbitrageScanner
from volatility_squeeze_engine import VolatilitySqueezeEngine


def test_parabolic_profit_steplock():
    # Long trade entered at $100
    entry = 100.0
    
    # Gain +2.0% -> below step-lock
    res1 = calculate_parabolic_steplock("BUY", entry, 102.0)
    assert not res1.is_updated

    # Gain +4.0% -> triggers +0.1% BE lock
    res2 = calculate_parabolic_steplock("BUY", entry, 104.0)
    assert res2.is_updated
    assert res2.locked_profit_pct == 0.1
    assert res2.new_sl_price == 100.1

    # Gain +6.0% -> triggers +3.0% profit lock
    res3 = calculate_parabolic_steplock("BUY", entry, 106.0)
    assert res3.is_updated
    assert res3.locked_profit_pct == 3.0
    assert res3.new_sl_price == 103.0

    # Gain +12.0% -> triggers +7.5% profit lock
    res4 = calculate_parabolic_steplock("BUY", entry, 112.0)
    assert res4.is_updated
    assert res4.locked_profit_pct == 7.5
    assert res4.new_sl_price == 107.5

    # Gain +25.0% -> triggers +16.0% profit lock
    res5 = calculate_parabolic_steplock("BUY", entry, 125.0)
    assert res5.is_updated
    assert res5.locked_profit_pct == 16.0
    assert res5.new_sl_price == 116.0


def test_triangular_arbitrage_scanner():
    scanner = TriangularArbitrageScanner(fee_bps_per_leg=2.0)
    # ETH/USDC = $2500, BTC/USDC = $50000 -> Synthetic ETH/BTC = 0.05
    # Actual ETH/BTC = 0.0520 (4% discrepancy = 400 bps)
    opp = scanner.scan_triangular_loop(
        p_a_usdc=2500.0,
        p_b_usdc=50000.0,
        p_a_b=0.0520,
        symbol_a="ETH",
        symbol_b="BTC",
        max_usd_size=200.0,
    )
    assert opp is not None
    assert opp.is_actionable
    assert opp.net_edge_bps > 10.0
    assert opp.estimated_profit_usd > 0.0


def test_volatility_squeeze_engine():
    engine = VolatilitySqueezeEngine(length=5, bb_mult=2.0, kc_mult=1.5)
    # Feed stable prices
    for i in range(10):
        engine.on_tick("ETH", 2500.0 + (i % 2), volume=10.0)
    
    # Volatility surge tick
    state = engine.on_tick("ETH", 2560.0, volume=50.0)
    assert state is not None
    assert state.symbol == "ETH"
    assert state.volume_ratio >= 2.0


def test_maritime_geopolitical_sniper():
    from maritime_geopolitical_sniper import MaritimeGeopoliticalSniper

    sniper = MaritimeGeopoliticalSniper()
    
    # 1. Red Sea / Hormuz oil tanker incident
    inc1 = sniper.evaluate_text("Breaking: Oil tanker attacked by drone strike near Bab el-Mandeb in Red Sea")
    assert inc1 is not None
    assert "BRENTOIL" in inc1.target_assets
    assert "WTI" in inc1.target_assets
    assert "NATGAS" in inc1.target_assets
    assert inc1.direction == "BULLISH"
    assert inc1.confidence >= 0.90

    # 2. Defense contract
    inc2 = sniper.evaluate_text("Pentagon awards $450M defense satellite launch contract to expanding contractor")
    assert inc2 is not None
    assert "PLTR" in inc2.target_assets or "RKLB" in inc2.target_assets
    assert inc2.direction == "BULLISH"

    # 3. Safe haven war escalation
    inc3 = sniper.evaluate_text("Emergency UN session called as air strikes launched following military invasion")
    assert inc3 is not None
    assert "XAU" in inc3.target_assets
    assert "XAG" in inc3.target_assets
