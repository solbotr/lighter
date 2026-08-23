#!/usr/bin/env python3
"""
Hawkes Process Order Clustering & Intensity (hawkes_order_intensity.py)
========================================================================
Implements the self-exciting mathematical Hawkes Point Process to model trade arrivals:
  λ(t) = μ + ∑_{t_i < t} α · e^(-β(t - t_i))

Key Functions:
- Differentiates between random noise wicks (λ(t) ≈ μ) and true cascade momentum (λ(t) >> μ)
- Computes Branching Ratio (n = α / β): If n > 0.70, a self-sustaining trend is unfolding
- Outputs Dynamic Kelly Conviction Multiplier (1.0x to 2.0x) for sniper execution
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("HawkesIntensity")


@dataclass
class TradeArrival:
    timestamp: float
    volume_usd: float
    side: str  # "BUY" or "SELL"


@dataclass
class HawkesIntensityState:
    symbol: str
    baseline_intensity_mu: float
    current_intensity_lambda: float
    branching_ratio: float
    is_cascade_active: bool
    sizing_multiplier: float
    dominant_side: str
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🌊 [HAWKES CLUSTER] {self.symbol} | Intensity λ(t): {self.current_intensity_lambda:.2f} (μ={self.baseline_intensity_mu:.2f}) | "
            f"Branching Ratio: {self.branching_ratio:.2f} | Cascade: {self.is_cascade_active} ({self.dominant_side}) | "
            f"Sizing Multiplier: {self.sizing_multiplier:.2f}x"
        )


class HawkesOrderIntensityEngine:
    """
    Hawkes Point Process Estimator for High-Frequency Crypto Microstructure.
    """

    def __init__(
        self,
        baseline_mu: float = 0.5,
        alpha: float = 1.2,
        beta: float = 1.8,
        decay_window_seconds: float = 30.0,
    ):
        self.baseline_mu = baseline_mu
        self.alpha = alpha
        self.beta = beta
        self.decay_window_seconds = decay_window_seconds
        self.trade_events: Dict[str, deque[TradeArrival]] = {}

    def register_trade(self, symbol: str, volume_usd: float, side: str, timestamp: Optional[float] = None) -> HawkesIntensityState:
        """
        Records a trade arrival and updates the self-exciting intensity function λ(t).
        """
        sym = symbol.upper()
        now = timestamp or time.time()

        if sym not in self.trade_events:
            self.trade_events[sym] = deque()

        q = self.trade_events[sym]
        q.append(TradeArrival(timestamp=now, volume_usd=volume_usd, side=side.upper()))

        # Prune old events outside decay window
        cutoff = now - self.decay_window_seconds
        while q and q[0].timestamp < cutoff:
            q.popleft()

        # Compute Hawkes intensity λ(t) = μ + ∑ α * exp(-β * Δt)
        intensity = self.baseline_mu
        buy_vol = 0.0
        sell_vol = 0.0

        for evt in q:
            dt = max(0.0, now - evt.timestamp)
            decay = math.exp(-self.beta * dt)
            intensity += (self.alpha * decay)
            if evt.side == "BUY":
                buy_vol += evt.volume_usd
            else:
                sell_vol += evt.volume_usd

        branching_ratio = self.alpha / self.beta if self.beta > 0 else 0.0
        is_cascade = intensity >= (self.baseline_mu * 3.0) and len(q) >= 5

        # Dynamic Sizing Multiplier: Scales between 1.0x (normal) and 2.0x (peak cascade)
        if is_cascade:
            sizing_mult = min(2.0, 1.0 + (intensity / (self.baseline_mu * 10.0)))
        else:
            sizing_mult = 1.0

        dominant = "BUY" if buy_vol >= sell_vol else "SELL"

        state = HawkesIntensityState(
            symbol=sym,
            baseline_intensity_mu=self.baseline_mu,
            current_intensity_lambda=round(intensity, 2),
            branching_ratio=round(branching_ratio, 2),
            is_cascade_active=is_cascade,
            sizing_multiplier=round(sizing_mult, 2),
            dominant_side=dominant,
        )
        return state
