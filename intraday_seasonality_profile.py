#!/usr/bin/env python3
"""
Intraday Seasonality Profile & Diurnal Normalizer (intraday_seasonality_profile.py)
==================================================================================
Models the empirical intraday U-shape volume and volatility curves (Diurnal Patterns):
  σ_norm(t) = σ_obs(t) / s(t)
  V_norm(t) = V_obs(t) / v(t)

Key Sessions:
- Asia Open (00:00 - 04:00 UTC): High volume, low trend persistence
- European Open (07:00 - 10:00 UTC): Institutional expansion
- US NY Cash Open & Overlap (13:30 - 16:30 UTC): Peak volatility crest (U-shape peak)
- US Post-Close Drift (21:00 - 23:00 UTC): Low volume, high spread widening

Key Capabilities:
- Normalizes order sizing and volatility thresholds based on time-of-day diurnal expectations
"""

from __future__ import annotations

import datetime
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("IntradaySeasonality")


@dataclass
class DiurnalSeasonalityMetrics:
    current_utc_hour: int
    session_name: str
    diurnal_volatility_multiplier: float  # Expected relative vol (e.g. 1.8x at NY open, 0.6x at quiet night)
    diurnal_volume_multiplier: float
    is_peak_liquidity_window: bool
    recommended_spread_multiplier: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"📅 [DIURNAL PROFILE] UTC {self.current_utc_hour:02d}:00 ({self.session_name}) | "
            f"Expected Vol: {self.diurnal_volatility_multiplier:.2f}x | Expected Volume: {self.diurnal_volume_multiplier:.2f}x | "
            f"Peak Liquidity: {self.is_peak_liquidity_window} | Spread Mult: {self.recommended_spread_multiplier:.2f}x"
        )


class IntradaySeasonalityProfileEngine:
    """
    Diurnal U-Shape Normalization Engine.
    """

    # 24-hour UTC relative volatility curve
    DIURNAL_VOL_CURVE = [
        1.10, 1.05, 0.95, 0.85, 0.75, 0.70, 0.80, 1.20,  # 00:00 - 07:00
        1.35, 1.25, 1.15, 1.05, 1.10, 1.65, 1.95, 1.85,  # 08:00 - 15:00 (NY Open spike)
        1.60, 1.40, 1.20, 1.00, 0.90, 0.80, 0.75, 0.90   # 16:00 - 23:00
    ]

    def evaluate_current_seasonality(self, utc_hour: Optional[int] = None) -> DiurnalSeasonalityMetrics:
        """
        Calculates diurnal multipliers for the current UTC hour.
        """
        if utc_hour is None:
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            h = now_dt.hour
        else:
            h = utc_hour % 24

        vol_mult = self.DIURNAL_VOL_CURVE[h]
        vol_u = vol_mult * 1.10  # Volume tracks volatility curve

        if 13 <= h <= 17:
            session = "US_NY_OPEN_PEAK"
            is_peak = True
            spread_mult = 0.80  # Spreads tightest during peak liquidity
        elif 7 <= h <= 11:
            session = "EUROPEAN_LONDON_OPEN"
            is_peak = True
            spread_mult = 0.90
        elif 0 <= h <= 4:
            session = "ASIA_TOKYO_OPEN"
            is_peak = False
            spread_mult = 1.00
        else:
            session = "QUIET_INTERSESSION_DRIFT"
            is_peak = False
            spread_mult = 1.25

        res = DiurnalSeasonalityMetrics(
            current_utc_hour=h,
            session_name=session,
            diurnal_volatility_multiplier=round(vol_mult, 2),
            diurnal_volume_multiplier=round(vol_u, 2),
            is_peak_liquidity_window=is_peak,
            recommended_spread_multiplier=round(spread_mult, 2),
        )
        return res
