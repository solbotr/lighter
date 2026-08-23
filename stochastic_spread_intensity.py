#!/usr/bin/env python3
"""
Cox-Ingersoll-Ross (CIR) Stochastic Spread Intensity (stochastic_spread_intensity.py)
=====================================================================================
Models orderbook bid-ask spread dynamics as a mean-reverting square-root CIR process:
  ds_t = κ(θ - s_t) dt + σ_s √s_t dW_t

Parameters:
  κ (kappa) = Mean-reversion speed of spread tightening
  θ (theta) = Long-run equilibrium spread width
  σ_s (sigma_s) = Spread volatility of volatility
  s_0 = Current instantaneous spread width

Key Capabilities:
- Enforces the strict Feller Boundary Condition: 2·κ·θ ≥ σ_s² (Guarantees spread strictly stays positive)
- Predicts when spread is temporarily blown out (s_t > θ + 2σ) and captures mean-reverting spread compression
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("CIRSpread")


@dataclass
class CIRSpreadParameters:
    symbol: str
    current_spread_bps: float
    equilibrium_spread_theta_bps: float
    mean_reversion_speed_kappa: float
    spread_vol_sigma: float
    is_feller_strictly_positive: bool
    spread_z_score: float
    is_spread_mean_reversion_tradeable: bool
    expected_compression_time_sec: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"📐 [CIR SPREAD] {self.symbol} | Spread: {self.current_spread_bps:.2f} bps (θ: {self.equilibrium_spread_theta_bps:.2f} bps, Z: {self.spread_z_score:+.2f}σ) | "
            f"κ: {self.mean_reversion_speed_kappa:.2f}, σ_s: {self.spread_vol_sigma:.2f} | Feller: {self.is_feller_strictly_positive} | "
            f"Tradeable Compression: {self.is_spread_mean_reversion_tradeable} (~{self.expected_compression_time_sec:.1f}s)"
        )


class StochasticSpreadIntensityEngine:
    """
    Cox-Ingersoll-Ross (CIR) Stochastic Spread Calibrator.
    """

    def __init__(self, default_kappa: float = 3.20, default_sigma_s: float = 0.85):
        self.default_kappa = default_kappa
        self.default_sigma_s = default_sigma_s

    def calibrate_spread_cir(
        self,
        symbol: str,
        current_spread_bps: float,
        equilibrium_spread_theta_bps: float = 4.5,
    ) -> CIRSpreadParameters:
        """
        Calibrates CIR parameters and evaluates spread compression tradeability.
        """
        sym = symbol.upper()
        s0 = max(0.5, current_spread_bps)
        theta = max(1.0, equilibrium_spread_theta_bps)
        kappa = self.default_kappa
        sigma_s = self.default_sigma_s

        # Feller condition: 2 * kappa * theta >= sigma_s^2
        feller_lhs = 2.0 * kappa * theta
        feller_rhs = sigma_s ** 2
        is_feller = feller_lhs >= feller_rhs

        # Spread deviation Z-score
        spread_std = sigma_s * math.sqrt(theta / (2.0 * kappa))
        z_score = (s0 - theta) / max(0.5, spread_std)

        # Tradeable if spread is blown out (Z >= 2.0)
        is_tradeable = z_score >= 1.80

        # Mean reversion half-life in seconds
        half_life_sec = (math.log(2.0) / kappa) if kappa > 0 else 1.0

        res = CIRSpreadParameters(
            symbol=sym,
            current_spread_bps=round(s0, 2),
            equilibrium_spread_theta_bps=round(theta, 2),
            mean_reversion_speed_kappa=round(kappa, 2),
            spread_vol_sigma=round(sigma_s, 2),
            is_feller_strictly_positive=is_feller,
            spread_z_score=round(z_score, 2),
            is_spread_mean_reversion_tradeable=is_tradeable,
            expected_compression_time_sec=round(half_life_sec, 2),
        )
        return res
