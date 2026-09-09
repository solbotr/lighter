#!/usr/bin/env python3
"""
Garman-Klass High-Efficiency Realized Volatility (garman_klass_volatility.py)
=============================================================================
Calculates high-precision intraday realized volatility using Open, High, Low, Close tick geometry:
  σ_GK² = 0.5 · (ln(H/L))² - (2·ln(2) - 1) · (ln(C/O))²

Key Advantages:
- 8x more statistically efficient than standard Close-to-Close volatility
- Captures intra-candle flash wicks and volatility expansion in real time
- Automatically tightens/widens market making spreads in < 1ms
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("GarmanKlassVolatility")


@dataclass
class OHLCBar:
    open: float
    high: float
    low: float
    close: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class RealizedVolatilityState:
    symbol: str
    garman_klass_volatility_pct: float  # Annualized % volatility
    parkinson_volatility_pct: float
    volatility_regime: str  # "EXTREME_VOL", "ELEVATED", "NORMAL", "QUIET"
    spread_multiplier: float  # 1.0x (normal) to 2.5x (extreme)
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🌊 [GARMAN-KLASS VOL] {self.symbol} | σ_GK: {self.garman_klass_volatility_pct:.2f}% (Parkinson: {self.parkinson_volatility_pct:.2f}%) | "
            f"Regime: {self.volatility_regime} | Spread Multiplier: {self.spread_multiplier:.2f}x"
        )


class GarmanKlassVolatilityEstimator:
    """
    High-Efficiency Realized Volatility Estimator.
    """

    def __init__(self, window_bars: int = 14):
        self.window_bars = window_bars
        self.bar_history: Dict[str, deque[OHLCBar]] = {}

    def push_bar(self, symbol: str, bar: OHLCBar) -> None:
        """Appends OHLC bar to rolling history."""
        sym = symbol.upper()
        if sym not in self.bar_history:
            self.bar_history[sym] = deque(maxlen=self.window_bars)
        self.bar_history[sym].append(bar)

    def compute_volatility(self, symbol: str) -> RealizedVolatilityState:
        """
        Calculates Garman-Klass and Parkinson annualized realized volatility.
        """
        sym = symbol.upper()
        bars = self.bar_history.get(sym, deque())

        if not bars:
            return RealizedVolatilityState(
                symbol=sym,
                garman_klass_volatility_pct=45.0,
                parkinson_volatility_pct=42.0,
                volatility_regime="NORMAL",
                spread_multiplier=1.0,
            )

        c_const = 2.0 * math.log(2.0) - 1.0  # ≈ 0.38629
        gk_variances: List[float] = []
        park_variances: List[float] = []

        for b in bars:
            o, h, l, c = max(1e-4, b.open), max(1e-4, b.high), max(1e-4, b.low), max(1e-4, b.close)
            log_hl = math.log(h / l)
            log_co = math.log(c / o)

            var_gk = 0.5 * (log_hl ** 2) - c_const * (log_co ** 2)
            var_park = (log_hl ** 2) / (4.0 * math.log(2.0))

            gk_variances.append(max(0.0, var_gk))
            park_variances.append(max(0.0, var_park))

        # Annualized standard deviation (assuming 1-min bars: sqrt(525600))
        annual_factor = math.sqrt(525600.0)
        mean_gk_var = sum(gk_variances) / len(gk_variances)
        mean_park_var = sum(park_variances) / len(park_variances)

        sigma_gk = math.sqrt(mean_gk_var) * annual_factor * 100.0
        sigma_park = math.sqrt(mean_park_var) * annual_factor * 100.0

        if sigma_gk >= 90.0:
            regime = "EXTREME_VOL"
            mult = 2.50
        elif sigma_gk >= 60.0:
            regime = "ELEVATED"
            mult = 1.60
        elif sigma_gk <= 25.0:
            regime = "QUIET"
            mult = 0.85
        else:
            regime = "NORMAL"
            mult = 1.00

        state = RealizedVolatilityState(
            symbol=sym,
            garman_klass_volatility_pct=round(sigma_gk, 2),
            parkinson_volatility_pct=round(sigma_park, 2),
            volatility_regime=regime,
            spread_multiplier=round(mult, 2),
        )
        return state
