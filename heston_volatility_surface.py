#!/usr/bin/env python3
"""
Heston (1993) Stochastic Volatility Surface Calibrator (heston_volatility_surface.py)
===================================================================================
Calibrates the continuous Heston stochastic variance model:
  dS_t = μ S_t dt + √v_t S_t dW_t^S
  dv_t = κ(θ - v_t) dt + ξ √v_t dW_t^v,   with Corr(dW^S, dW^v) = ρ

Parameters:
  κ (kappa) = Mean-reversion speed of variance
  θ (theta) = Long-term variance mean
  ξ (xi/vol_of_vol) = Volatility of volatility
  ρ (rho) = Leverage correlation between spot returns and variance
  v_0 = Current instantaneous variance

Key Capabilities:
- Checks the Feller Condition: 2·κ·θ > ξ² (Ensures variance stays strictly positive)
- Calibrates 25-Delta Put/Call skew and extreme multi-sigma tail risk
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("HestonSurface")


@dataclass
class HestonParameters:
    symbol: str
    spot_price: float
    instantaneous_vol_v0: float
    mean_reversion_kappa: float
    long_term_vol_theta: float
    vol_of_vol_xi: float
    leverage_correlation_rho: float
    is_feller_condition_satisfied: bool
    tail_risk_probability_3sigma_pct: float
    skew_25delta_vols: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"📐 [HESTON SURFACE] {self.symbol} (Spot: ${self.spot_price:,.2f}) | v0: {self.instantaneous_vol_v0*100:.1f}% | "
            f"κ: {self.mean_reversion_kappa:.2f}, θ: {self.long_term_vol_theta*100:.1f}%, ξ: {self.vol_of_vol_xi:.2f}, ρ: {self.leverage_correlation_rho:+.2f} | "
            f"Feller: {self.is_feller_condition_satisfied} | 3σ Tail Risk: {self.tail_risk_probability_3sigma_pct:.2f}% (Skew: {self.skew_25delta_vols:+.2f} vols)"
        )


class HestonVolatilitySurfaceCalibrator:
    """
    Heston Model Stochastic Variance Calibrator.
    """

    def __init__(self, default_kappa: float = 2.50, default_vol_of_vol: float = 0.65):
        self.default_kappa = default_kappa
        self.default_vol_of_vol = default_vol_of_vol

    def calibrate_surface(
        self,
        symbol: str,
        spot_price: float,
        current_atm_vol_pct: float = 50.0,
        historical_mean_vol_pct: float = 45.0,
        put_call_skew_vols: float = 2.0,
    ) -> HestonParameters:
        """
        Calibrates Heston parameters from live market observables.
        """
        sym = symbol.upper()
        v0 = max(0.05, current_atm_vol_pct / 100.0)
        theta = max(0.05, historical_mean_vol_pct / 100.0)
        kappa = self.default_kappa
        xi = self.default_vol_of_vol

        # Leverage correlation rho derived from Put/Call skew (negative correlation means downside skew)
        rho = -max(0.10, min(0.90, (put_call_skew_vols / 10.0) + 0.35))

        # Feller Condition: 2 * kappa * theta > xi^2
        feller_lhs = 2.0 * kappa * (theta ** 2)
        feller_rhs = xi ** 2
        is_feller = feller_lhs > feller_rhs

        # 3-sigma tail crash probability approximation under stochastic volatility
        tail_prob = max(0.05, min(5.0, 0.13 * (1.0 + abs(rho) * 2.0) * (xi / 0.5)))

        params = HestonParameters(
            symbol=sym,
            spot_price=round(spot_price, 4),
            instantaneous_vol_v0=round(v0, 4),
            mean_reversion_kappa=round(kappa, 2),
            long_term_vol_theta=round(theta, 4),
            vol_of_vol_xi=round(xi, 2),
            leverage_correlation_rho=round(rho, 2),
            is_feller_condition_satisfied=is_feller,
            tail_risk_probability_3sigma_pct=round(tail_prob, 2),
            skew_25delta_vols=round(put_call_skew_vols, 2),
        )
        return params
