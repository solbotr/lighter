#!/usr/bin/env python3
"""
Deribit Options IV & Gamma Skew Modeler (iv_surface_skew.py)
============================================================
Derives institutional smart-money sentiment from real-time Deribit Options metrics:
- 25-Delta Call/Put Volatility Skew: Skew = 25d_Put_IV - 25d_Call_IV
- Term Structure Ratio (Front-month IV / Back-month IV)
- Smart Money Hedging Alert: If Put Skew > +6.0 vols, signals high-probability breakdown risk
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("IVSurfaceSkew")


@dataclass
class OptionsSkewMetrics:
    symbol: str
    atm_iv: float
    put_25d_iv: float
    call_25d_iv: float
    skew_25d_vol: float  # Put IV - Call IV (Positive = Bearish Smart Money Hedging)
    term_structure_ratio: float
    sentiment_regime: str  # "EXTREME_BEAR_HEDGING", "MODERATE_BEAR", "NEUTRAL", "BULL_GREED"
    tighten_long_stops: bool = False
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"📊 [IV SKEW] {self.symbol} | ATM IV: {self.atm_iv:.1f}% | 25d Skew: {self.skew_25d_vol:+.2f} vols | "
            f"Regime: {self.sentiment_regime} | Tighten Long Stops: {self.tighten_long_stops}"
        )


class IVSurfaceSkewModeler:
    """
    Options Volatility Surface & Tail Risk Modeler.
    """

    def __init__(self, high_skew_threshold_vols: float = 5.0):
        self.high_skew_threshold_vols = high_skew_threshold_vols
        self.latest_skews: Dict[str, OptionsSkewMetrics] = {}

    def update_surface_quotes(
        self,
        symbol: str,
        atm_iv: float,
        put_25d_iv: float,
        call_25d_iv: float,
        front_month_iv: float,
        back_month_iv: float,
    ) -> OptionsSkewMetrics:
        """
        Calculates 25-delta Put/Call volatility skew and market regime.
        """
        sym = symbol.upper()
        skew_vols = put_25d_iv - call_25d_iv
        term_ratio = front_month_iv / back_month_iv if back_month_iv > 0 else 1.0

        if skew_vols >= self.high_skew_threshold_vols:
            regime = "EXTREME_BEAR_HEDGING"
            tighten_stops = True
        elif skew_vols >= 2.0:
            regime = "MODERATE_BEAR"
            tighten_stops = False
        elif skew_vols <= -2.0:
            regime = "BULL_GREED"
            tighten_stops = False
        else:
            regime = "NEUTRAL"
            tighten_stops = False

        metrics = OptionsSkewMetrics(
            symbol=sym,
            atm_iv=round(atm_iv, 2),
            put_25d_iv=round(put_25d_iv, 2),
            call_25d_iv=round(call_25d_iv, 2),
            skew_25d_vol=round(skew_vols, 2),
            term_structure_ratio=round(term_ratio, 2),
            sentiment_regime=regime,
            tighten_long_stops=tighten_stops,
        )
        self.latest_skews[sym] = metrics
        return metrics
