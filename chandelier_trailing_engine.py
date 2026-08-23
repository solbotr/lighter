#!/usr/bin/env python3
"""
Chandelier Volatility-Envelope Trailing Runner (chandelier_trailing_engine.py)
=============================================================================
Institutional volatility-adaptive exit manager based on the Chandelier Exit model:
- Chandelier Long Exit = Highest High(22) - k * ATR(14)
- Chandelier Short Exit = Lowest Low(22) + k * ATR(14)

Key Capabilities:
- Dynamic Trend-Ride Expansion: Expands multiplier k from 2.0x -> 3.5x during high-conviction catalyst surges
- Volatility Envelope Clamping: Tightens stop when momentum stalls or volatility contracts
- Multi-Stage Integration: Seamlessly manages the remaining 25% runner position after TP1/TP2
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ChandelierTrailing")


@dataclass
class CandleBar:
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ChandelierStopState:
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    highest_high: float
    lowest_low: float
    current_atr: float
    stop_price: float
    atr_multiplier: float
    unrealized_pnl_pct: float
    is_triggered: bool = False
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🌊 [CHANDELIER STOP] {self.symbol} {self.side} | Entry: ${self.entry_price:,.2f} | "
            f"Trailing Floor: ${self.stop_price:,.2f} (k={self.atr_multiplier:.1f}x, ATR=${self.current_atr:,.2f}) | "
            f"uPnL: {self.unrealized_pnl_pct:+.2f}%"
        )


class ChandelierTrailingEngine:
    """
    Computes dynamic Chandelier Volatility Envelope stops to capture full macro momentum.
    """

    def __init__(
        self,
        atr_period: int = 14,
        lookback_period: int = 22,
        base_multiplier: float = 2.5,
        catalyst_expansion_multiplier: float = 3.5,
    ):
        self.atr_period = atr_period
        self.lookback_period = lookback_period
        self.base_multiplier = base_multiplier
        self.catalyst_expansion_multiplier = catalyst_expansion_multiplier
        self.candle_history: Dict[str, deque[CandleBar]] = {}
        self.active_chandelier_positions: Dict[str, ChandelierStopState] = {}

    def push_candle(self, symbol: str, candle: CandleBar) -> None:
        """Appends a new 1-minute candle bar to history."""
        sym = symbol.upper()
        if sym not in self.candle_history:
            self.candle_history[sym] = deque(maxlen=self.lookback_period + self.atr_period + 5)
        self.candle_history[sym].append(candle)

    def compute_atr(self, symbol: str) -> float:
        """Calculates 14-period Average True Range."""
        sym = symbol.upper()
        candles = self.candle_history.get(sym, deque())
        if len(candles) < 2:
            return candles[-1].close * 0.015 if candles else 1.0

        tr_values: List[float] = []
        c_list = list(candles)
        for i in range(1, len(c_list)):
            curr = c_list[i]
            prev = c_list[i - 1]
            tr = max(
                curr.high - curr.low,
                abs(curr.high - prev.close),
                abs(curr.low - prev.close),
            )
            tr_values.append(tr)

        lookback = min(self.atr_period, len(tr_values))
        return sum(tr_values[-lookback:]) / lookback if lookback > 0 else 1.0

    def update_runner_stop(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        is_catalyst_active: bool = False,
    ) -> ChandelierStopState:
        """
        Updates the Chandelier Volatility Envelope trailing stop for an active runner.
        """
        sym = symbol.upper()
        candles = self.candle_history.get(sym, deque())

        # If insufficient candle history, synthesize from current and entry price
        if not candles:
            highest_h = max(entry_price, current_price)
            lowest_l = min(entry_price, current_price)
            atr = current_price * 0.012
        else:
            c_list = list(candles)
            highest_h = max([c.high for c in c_list[-self.lookback_period :]] + [current_price])
            lowest_l = min([c.low for c in c_list[-self.lookback_period :]] + [current_price])
            atr = self.compute_atr(sym)

        # Scale multiplier if major catalyst momentum is surging
        k = self.catalyst_expansion_multiplier if is_catalyst_active else self.base_multiplier
        is_long = side.upper().startswith("LONG") or side.upper().startswith("BUY")

        if is_long:
            stop_px = highest_h - (k * atr)
            # Never drop below breakeven if already in heavy profit
            if current_price >= entry_price * 1.025:
                stop_px = max(stop_px, entry_price * 1.002)
            is_triggered = current_price <= stop_px
            pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
        else:
            stop_px = lowest_l + (k * atr)
            if current_price <= entry_price * 0.975:
                stop_px = min(stop_px, entry_price * 0.998)
            is_triggered = current_price >= stop_px
            pnl_pct = ((entry_price - current_price) / entry_price) * 100.0

        # Monotonic trailing floor (stop only tightens, never loosens)
        prev_state = self.active_chandelier_positions.get(sym)
        if prev_state and not is_triggered:
            if is_long:
                stop_px = max(stop_px, prev_state.stop_price)
            else:
                stop_px = min(stop_px, prev_state.stop_price)

        state = ChandelierStopState(
            symbol=sym,
            side="LONG" if is_long else "SHORT",
            entry_price=entry_price,
            highest_high=highest_h,
            lowest_low=lowest_l,
            current_atr=round(atr, 4),
            stop_price=round(stop_px, 4),
            atr_multiplier=k,
            unrealized_pnl_pct=round(pnl_pct, 2),
            is_triggered=is_triggered,
        )
        self.active_chandelier_positions[sym] = state
        return state
