#!/usr/bin/env python3
"""
Markov Jump Copula & Cross-Asset Tail Dependence (markov_jump_copula.py)
========================================================================
Models non-linear tail dependence across BTC, ETH, SOL, and HYPE using dynamic Clayton/Gumbel Copulas:
  Lower Tail Dependence: λ_L = 2^{-1/θ_clayton}
  Upper Tail Dependence: λ_U = 2 - 2^{1/θ_gumbel}

Key Capabilities:
- Detects asymmetric co-crash risk (when lower tail dependence λ_L spikes to > 0.70)
- Identifies asset decoupling (when altcoin tail dependence breaks down < 0.20), triggering relative-value stat-arb
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("MarkovCopula")


@dataclass
class CopulaTailDependence:
    pair_name: str
    clayton_theta: float
    gumbel_theta: float
    lower_tail_dependence_lambda_l: float  # Downside co-crash risk
    upper_tail_dependence_lambda_u: float  # Upside co-boom probability
    is_decoupled: bool
    is_systemic_crash_risk: bool
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🧠 [MARKOV COPULA] {self.pair_name} | Downside λ_L: {self.lower_tail_dependence_lambda_l:.3f} | "
            f"Upside λ_U: {self.upper_tail_dependence_lambda_u:.3f} | Decoupled: {self.is_decoupled} | "
            f"Systemic Crash Risk: {self.is_systemic_crash_risk}"
        )


class MarkovJumpCopulaEngine:
    """
    Non-Linear Copula Tail Dependence Estimator.
    """

    def __init__(self, history_len: int = 30):
        self.history_len = history_len
        self.return_series: Dict[str, deque[Tuple[float, float]]] = {}  # pair -> (r1, r2)

    def push_paired_returns(self, asset1: str, asset2: str, r1_bps: float, r2_bps: float) -> None:
        """Records paired returns for copula parameter estimation."""
        pair = f"{asset1.upper()}_{asset2.upper()}"
        if pair not in self.return_series:
            self.return_series[pair] = deque(maxlen=self.history_len)
        self.return_series[pair].append((r1_bps, r2_bps))

    def estimate_tail_dependence(self, asset1: str, asset2: str) -> CopulaTailDependence:
        """
        Calculates lower and upper tail dependence using Kendall's tau correlation mapping.
        """
        a1 = asset1.upper()
        a2 = asset2.upper()
        pair = f"{a1}_{a2}"
        series = self.return_series.get(pair, deque())

        if len(series) < 5:
            # Baseline calibration
            tau = 0.65
        else:
            # Concordance ranking
            x = [s[0] for s in series]
            y = [s[1] for s in series]
            n = len(series)
            concordant = 0
            discordant = 0
            for i in range(n):
                for j in range(i + 1, n):
                    dx = x[i] - x[j]
                    dy = y[i] - y[j]
                    if dx * dy > 0:
                        concordant += 1
                    elif dx * dy < 0:
                        discordant += 1
            tot = concordant + discordant
            tau = (concordant - discordant) / tot if tot > 0 else 0.50

        tau = max(0.05, min(0.95, tau))

        # Clayton Theta: θ = 2·τ / (1 - τ)
        theta_c = max(0.1, (2.0 * tau) / (1.0 - tau))
        # Gumbel Theta: θ = 1 / (1 - τ)
        theta_g = max(1.1, 1.0 / (1.0 - tau))

        # Lower Tail: λ_L = 2^(-1/θ_c)
        lambda_l = 2.0 ** (-1.0 / theta_c)
        # Upper Tail: λ_U = 2 - 2^(1/θ_g)
        lambda_u = max(0.0, 2.0 - (2.0 ** (1.0 / theta_g)))

        decoupled = lambda_l < 0.25 and tau < 0.35
        systemic = lambda_l >= 0.70

        res = CopulaTailDependence(
            pair_name=pair,
            clayton_theta=round(theta_c, 3),
            gumbel_theta=round(theta_g, 3),
            lower_tail_dependence_lambda_l=round(lambda_l, 3),
            upper_tail_dependence_lambda_u=round(lambda_u, 3),
            is_decoupled=decoupled,
            is_systemic_crash_risk=systemic,
        )
        return res
