#!/usr/bin/env python3
"""
Unit Tests for Macro Basket Batch Sniper (test_macro_basket_sniper.py)
======================================================================
"""

from __future__ import annotations

import asyncio
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from macro_basket_sniper import (
    MacroBasketBatchSniper,
    MacroEventType,
    MacroBasketPlan,
)


def test_classify_macro_event_fomc():
    engine = MacroBasketBatchSniper()
    meta = engine.classify_macro_event("Fed announces 50 basis points rate cut as inflation eases")
    assert meta is not None
    event_type, direction = meta
    assert event_type == MacroEventType.FED_RATE_DECISION
    assert direction == "BUY"


def test_classify_macro_event_tariff():
    engine = MacroBasketBatchSniper()
    meta = engine.classify_macro_event("Trade tariffs imposed on foreign goods by administration")
    assert meta is not None
    event_type, direction = meta
    assert event_type == MacroEventType.TARIFF_TRADE_WAR
    assert direction == "SELL"


def test_build_macro_basket_plan_allocations():
    engine = MacroBasketBatchSniper(default_basket_capital_usd=200.0)
    plan = engine.build_macro_basket_plan("SEC approves crypto framework and broad market ETFs")
    assert plan is not None
    assert plan.total_basket_usd == 200.0
    assert len(plan.allocations) == 5

    # Check weights: BTC=35%, ETH=25%, SOL=20%, HYPE=10%, DOGE=10%
    symbols = {a.symbol: a.target_usd for a in plan.allocations}
    assert symbols["BTC"] == 70.0
    assert symbols["ETH"] == 50.0
    assert symbols["SOL"] == 40.0
    assert symbols["HYPE"] == 20.0
    assert symbols["DOGE"] == 20.0


@pytest.mark.asyncio
async def test_execute_macro_basket_parallel():
    engine = MacroBasketBatchSniper(default_basket_capital_usd=100.0)
    plan = engine.build_macro_basket_plan("Federal Reserve cuts interest rates by 25 bps")
    assert plan is not None

    executed_plan = await engine.execute_macro_basket_parallel(plan)
    assert len(executed_plan.executed_orders) == 5
    assert engine.total_macro_baskets_fired == 1
    assert engine.total_macro_volume_usd == 100.0

    html = engine.format_macro_report_html(executed_plan)
    assert "MACRO BASKET SNIPER EXECUTED" in html
    assert "$BTC" in html
