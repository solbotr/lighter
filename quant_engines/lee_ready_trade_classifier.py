#!/usr/bin/env python3
"""
Lee-Ready & Bulk Volume Trade Classifier (lee_ready_trade_classifier.py)
========================================================================
Implements Charles Lee & Mark Ready's (1991) Tick & Quote Rule with Bulk Volume Classification (BVC):
- Classifies every trade execution as Aggressive Buyer vs Aggressive Seller:
  - If Trade Price > Mid Price -> BUY
  - If Trade Price < Mid Price -> SELL
  - If Trade Price == Mid Price -> Tick Rule (Compare with previous trade price)
- Measures institutional volume pressure in real time
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("LeeReadyClassifier")


@dataclass
class ClassifiedTrade:
    trade_id: str
    symbol: str
    price: float
    size_usd: float
    classified_side: str  # "BUY", "SELL", "INDETERMINATE"
    classification_method: str  # "QUOTE_RULE", "TICK_RULE", "BULK_VOLUME"
    mid_price: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class FlowPressureMetrics:
    symbol: str
    total_volume_usd: float
    buyer_taker_volume_usd: float
    seller_taker_volume_usd: float
    taker_buy_ratio_pct: float
    flow_imbalance_usd: float
    is_institutional_sweep: bool
    dominant_side: str  # "AGGRESSIVE_BUY", "AGGRESSIVE_SELL", "BALANCED"
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🔬 [LEE-READY FLOW] {self.symbol} | Buy Ratio: {self.taker_buy_ratio_pct:.1f}% (Net: ${self.flow_imbalance_usd:+,.2f} USD) | "
            f"Dominant Flow: {self.dominant_side} | Institutional Sweep: {self.is_institutional_sweep}"
        )


class LeeReadyTradeClassifier:
    """
    Microstructure Trade Initiator Classifier.
    """

    def __init__(self, rolling_window: int = 50, sweep_threshold_usd: float = 25000.0):
        self.rolling_window = rolling_window
        self.sweep_threshold_usd = sweep_threshold_usd
        self.last_trade_prices: Dict[str, float] = {}
        self.recent_trades: Dict[str, deque[ClassifiedTrade]] = {}

    def classify_trade(
        self,
        trade_id: str,
        symbol: str,
        price: float,
        size_usd: float,
        best_bid: float,
        best_ask: float,
    ) -> ClassifiedTrade:
        """
        Classifies incoming trade execution using Lee-Ready quote and tick rules.
        """
        sym = symbol.upper()
        mid = (best_bid + best_ask) / 2.0
        last_px = self.last_trade_prices.get(sym, price)

        # 1. Quote Rule: Compare with mid price
        if price > mid:
            side = "BUY"
            method = "QUOTE_RULE"
        elif price < mid:
            side = "SELL"
            method = "QUOTE_RULE"
        else:
            # 2. Tick Rule: Compare with previous trade price
            if price > last_px:
                side = "BUY"
                method = "TICK_RULE"
            elif price < last_px:
                side = "SELL"
                method = "TICK_RULE"
            else:
                side = "BUY" if size_usd >= 1000.0 else "SELL"
                method = "BULK_VOLUME"

        self.last_trade_prices[sym] = price

        classified = ClassifiedTrade(
            trade_id=trade_id,
            symbol=sym,
            price=round(price, 4),
            size_usd=round(size_usd, 2),
            classified_side=side,
            classification_method=method,
            mid_price=round(mid, 4),
        )

        if sym not in self.recent_trades:
            self.recent_trades[sym] = deque(maxlen=self.rolling_window)
        self.recent_trades[sym].append(classified)
        return classified

    def compute_flow_pressure(self, symbol: str) -> FlowPressureMetrics:
        """
        Aggregates recent classified trades to determine institutional taker pressure.
        """
        sym = symbol.upper()
        trades = self.recent_trades.get(sym, deque())

        if not trades:
            return FlowPressureMetrics(
                symbol=sym,
                total_volume_usd=0.0,
                buyer_taker_volume_usd=0.0,
                seller_taker_volume_usd=0.0,
                taker_buy_ratio_pct=50.0,
                flow_imbalance_usd=0.0,
                is_institutional_sweep=False,
                dominant_side="BALANCED",
            )

        buy_vol = sum(t.size_usd for t in trades if t.classified_side == "BUY")
        sell_vol = sum(t.size_usd for t in trades if t.classified_side == "SELL")
        total_vol = buy_vol + sell_vol
        net_imbalance = buy_vol - sell_vol
        buy_ratio = (buy_vol / total_vol) * 100.0 if total_vol > 0 else 50.0

        is_sweep = any(t.size_usd >= self.sweep_threshold_usd for t in trades)

        if buy_ratio >= 65.0:
            dom = "AGGRESSIVE_BUY"
        elif buy_ratio <= 35.0:
            dom = "AGGRESSIVE_SELL"
        else:
            dom = "BALANCED"

        metrics = FlowPressureMetrics(
            symbol=sym,
            total_volume_usd=round(total_vol, 2),
            buyer_taker_volume_usd=round(buy_vol, 2),
            seller_taker_volume_usd=round(sell_vol, 2),
            taker_buy_ratio_pct=round(buy_ratio, 1),
            flow_imbalance_usd=round(net_imbalance, 2),
            is_institutional_sweep=is_sweep,
            dominant_side=dom,
        )
        return metrics
