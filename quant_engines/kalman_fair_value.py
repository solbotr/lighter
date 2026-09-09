#!/usr/bin/env python3
"""
State-Space Kalman Filter Fair Value Tracker (kalman_fair_value.py)
==================================================================
Fuses noisy tick observations across multiple venues (zkLighter, Hyperliquid, Binance, Bybit)
into a continuous single Latent Fair Value:
  State Equation:       x_t = x_{t-1} + w_t,      w_t ~ N(0, Q)
  Measurement Equation: z_t = x_t + v_t,          v_t ~ N(0, R_venue)

Key Capabilities:
- Dynamic venue noise variance R_venue (Binance lowest noise, thin books higher noise)
- Instantaneous Z-score mispricing detection:
  Z = (zkLighter_Mid - Kalman_Fair_Value) / sqrt(P_t)
- Fires mean-reversion snipes when |Z| ≥ 2.0σ
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("KalmanFairValue")


@dataclass
class KalmanState:
    symbol: str
    estimated_fair_value: float
    estimation_variance_p: float
    latest_z_score: float
    is_mispriced: bool
    mispricing_direction: str  # "UNDERVALUED_BUY", "OVERVALUED_SELL", "FAIR"
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🧠 [KALMAN FAIR VALUE] {self.symbol} | Fair Value: ${self.estimated_fair_value:,.2f} (σ={math.sqrt(self.estimation_variance_p):.3f}) | "
            f"Z-Score: {self.latest_z_score:+.2f}σ | State: {self.mispricing_direction}"
        )


class KalmanFairValueTracker:
    """
    1D State-Space Kalman Filter for Multi-Exchange Price Discovery.
    """

    # Measurement Noise Variance R per Venue
    VENUE_NOISE_R: Dict[str, float] = {
        "BINANCE": 0.05,        # Highest liquidity, cleanest price discovery
        "BYBIT": 0.08,
        "HYPERLIQUID": 0.12,
        "ZKLIGHTER": 0.20,      # L2 orderbook, higher noise variance
    }

    def __init__(
        self,
        process_noise_q: float = 0.01,
        z_score_trigger_threshold: float = 2.0,
    ):
        self.process_noise_q = process_noise_q
        self.z_score_trigger_threshold = z_score_trigger_threshold
        self.state_x: Dict[str, float] = {}  # Estimated fair value
        self.variance_p: Dict[str, float] = {}  # Estimation error variance

    def update_venue_price(
        self,
        symbol: str,
        venue: str,
        observed_price: float,
    ) -> KalmanState:
        """
        Updates the Kalman filter state with a new venue observation.
        """
        sym = symbol.upper()
        ven = venue.upper()
        r = self.VENUE_NOISE_R.get(ven, 0.15)

        # Initialize state if new
        if sym not in self.state_x:
            self.state_x[sym] = observed_price
            self.variance_p[sym] = 1.0

        x_prev = self.state_x[sym]
        p_prev = self.variance_p[sym]

        # 1. Time Update (Predict)
        x_pred = x_prev
        p_pred = p_prev + self.process_noise_q

        # 2. Measurement Update (Correct)
        # Kalman Gain K = P_pred / (P_pred + R)
        k_gain = p_pred / (p_pred + r)
        residual = observed_price - x_pred
        x_new = x_pred + (k_gain * residual)
        p_new = (1.0 - k_gain) * p_pred

        self.state_x[sym] = x_new
        self.variance_p[sym] = p_new

        # Compute Z-score mispricing against current observed price
        std_dev = math.sqrt(max(1e-6, p_new + r))
        z_score = (observed_price - x_new) / std_dev

        if z_score <= -self.z_score_trigger_threshold:
            dir_str = "UNDERVALUED_BUY"
            is_mis = True
        elif z_score >= self.z_score_trigger_threshold:
            dir_str = "OVERVALUED_SELL"
            is_mis = True
        else:
            dir_str = "FAIR"
            is_mis = False

        state = KalmanState(
            symbol=sym,
            estimated_fair_value=round(x_new, 4),
            estimation_variance_p=round(p_new, 6),
            latest_z_score=round(z_score, 2),
            is_mispriced=is_mis,
            mispricing_direction=dir_str,
        )
        return state
