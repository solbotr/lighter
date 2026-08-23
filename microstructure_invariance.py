#!/usr/bin/env python3
"""
Kyle & Obizhaeva Market Microstructure Invariance (microstructure_invariance.py)
================================================================================
Implements Albert S. Kyle & Anna A. Obizhaeva's (2016) Microstructure Invariance:
  Business Time / Invariant Activity: L = (P · V / σ)^(2/3)
  Invariant Order Size: Q_inv = (P · V / σ)^(1/3)

Key Capabilities:
- Normalizes order sizing and execution schedules across diverse market volatility regimes
- Allows the bot to automatically scale trading aggressiveness proportionally to true economic trade arrival speed
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("MicrostructureInvariance")


@dataclass
class InvarianceMetrics:
    symbol: str
    price: float
    volume_24h_usd: float
    volatility_sigma: float
    invariant_liquidity_L: float
    invariant_order_size_usd: float
    recommended_trade_chunk_usd: float
    optimal_execution_horizon_sec: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"⚡ [INVARIANCE] {self.symbol} | Activity L: {self.invariant_liquidity_L:,.0f} | "
            f"Invariant Order Size: ${self.invariant_order_size_usd:,.2f} USD | "
            f"Rec Chunk: ${self.recommended_trade_chunk_usd:,.2f} USD (Horizon: {self.optimal_execution_horizon_sec:.1f}s)"
        )


class MicrostructureInvarianceEngine:
    """
    Kyle-Obizhaeva Microstructure Invariance Model.
    """

    def __init__(self, target_trade_risk_fraction: float = 0.05):
        self.target_trade_risk_fraction = target_trade_risk_fraction

    def compute_invariance_parameters(
        self,
        symbol: str,
        price: float,
        volume_24h_usd: float,
        volatility_sigma: float = 0.03,  # Daily std dev
    ) -> InvarianceMetrics:
        """
        Calculates invariant liquidity unit L and optimal order chunk size.
        """
        sym = symbol.upper()
        p = max(0.0001, price)
        v = max(1000.0, volume_24h_usd)
        sigma = max(0.001, volatility_sigma)

        # Invariant Activity: L = (V / sigma)^(2/3)
        activity_ratio = v / sigma
        L = activity_ratio ** (2.0 / 3.0)

        # Invariant Order Size: Q_inv ≈ (V / sigma)^(1/3) * constant
        q_inv = (activity_ratio ** (1.0 / 3.0)) * 0.05
        chunk_usd = max(10.0, min(500.0, q_inv * self.target_trade_risk_fraction))

        # Optimal Horizon: T_opt ≈ (Q / V) * (1 / sigma)
        opt_horizon = max(2.0, min(60.0, (chunk_usd / (v / 86400.0)) * 0.5))

        metrics = InvarianceMetrics(
            symbol=sym,
            price=round(p, 4),
            volume_24h_usd=round(v, 2),
            volatility_sigma=round(sigma, 4),
            invariant_liquidity_L=round(L, 2),
            invariant_order_size_usd=round(q_inv, 2),
            recommended_trade_chunk_usd=round(chunk_usd, 2),
            optimal_execution_horizon_sec=round(opt_horizon, 2),
        )
        return metrics
