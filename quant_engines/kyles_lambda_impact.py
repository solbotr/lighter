#!/usr/bin/env python3
"""
Kyle's Lambda Microstructure Price Impact Estimator (kyles_lambda_impact.py)
===========================================================================
Implements Albert S. Kyle's (1985) market microstructure price impact equation:
  ΔP = λ · Q + ε
  λ = Cov(ΔP, Q) / Var(Q) = 2 · σ_v / σ_u

Key Capabilities:
- Estimates instantaneous market elasticity (how many bps of slippage an order of size Q will cause)
- Dynamically bounds requested trade notional to keep market impact ≤ target slippage cap (e.g. ≤ 15 bps)
- Prevents the bot's own orders from pushing the orderbook against itself
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("KylesLambda")


@dataclass
class TradeImpactObservation:
    order_flow_usd: float  # Signed order flow (+ for Buy, - for Sell)
    price_change_bps: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class PriceImpactEstimate:
    symbol: str
    lambda_impact_coefficient: float  # bps per $1,000 notional
    expected_impact_bps: float
    max_safe_size_usd: float
    orderbook_liquidity_elasticity: str  # "HIGH_LIQUIDITY", "NORMAL", "THIN_BOOK"
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"⚡ [KYLE'S LAMBDA] {self.symbol} | λ: {self.lambda_impact_coefficient:.4f} bps/$1k | "
            f"Expected Impact: {self.expected_impact_bps:.1f} bps | Max Safe Size: ${self.max_safe_size_usd:,.2f} USD | "
            f"State: {self.orderbook_liquidity_elasticity}"
        )


class KylesLambdaImpactEstimator:
    """
    Microstructure Price Impact Estimator.
    """

    def __init__(self, rolling_window: int = 30, max_allowable_impact_bps: float = 20.0):
        self.rolling_window = rolling_window
        self.max_allowable_impact_bps = max_allowable_impact_bps
        self.trade_history: Dict[str, deque[TradeImpactObservation]] = {}

    def register_trade_observation(
        self,
        symbol: str,
        order_flow_usd: float,
        price_change_bps: float,
    ) -> None:
        """Records signed order flow and resulting price change in basis points."""
        sym = symbol.upper()
        if sym not in self.trade_history:
            self.trade_history[sym] = deque(maxlen=self.rolling_window)
        self.trade_history[sym].append(
            TradeImpactObservation(order_flow_usd=order_flow_usd, price_change_bps=price_change_bps)
        )

    def compute_lambda(self, symbol: str) -> float:
        """
        Calculates Kyle's Lambda λ = Cov(ΔP, Q) / Var(Q).
        Returns basis points of impact per $1,000 traded.
        """
        sym = symbol.upper()
        obs = self.trade_history.get(sym, deque())
        if len(obs) < 5:
            return 0.05  # Default baseline 0.05 bps / $1k

        flows = [o.order_flow_usd for o in obs]
        deltas = [o.price_change_bps for o in obs]

        mean_f = sum(flows) / len(flows)
        mean_d = sum(deltas) / len(deltas)

        cov = sum((flows[i] - mean_f) * (deltas[i] - mean_d) for i in range(len(flows)))
        var_f = sum((f - mean_f) ** 2 for f in flows)

        if var_f <= 1e-6:
            return 0.05

        raw_lambda = cov / var_f  # bps per $1
        lambda_per_1k = max(0.001, raw_lambda * 1000.0)
        return lambda_per_1k

    def estimate_order_impact(self, symbol: str, requested_size_usd: float) -> PriceImpactEstimate:
        """
        Estimates expected basis point impact and bounds safe execution size.
        """
        sym = symbol.upper()
        lambda_k = self.compute_lambda(sym)

        # Expected impact = λ * (size / 1000)
        est_impact = lambda_k * (requested_size_usd / 1000.0)

        # Max safe size = (max_bps / λ) * 1000
        max_safe = (self.max_allowable_impact_bps / lambda_k) * 1000.0

        if lambda_k <= 0.03:
            elasticity = "HIGH_LIQUIDITY"
        elif lambda_k <= 0.10:
            elasticity = "NORMAL"
        else:
            elasticity = "THIN_BOOK"

        estimate = PriceImpactEstimate(
            symbol=sym,
            lambda_impact_coefficient=round(lambda_k, 4),
            expected_impact_bps=round(est_impact, 2),
            max_safe_size_usd=round(max_safe, 2),
            orderbook_liquidity_elasticity=elasticity,
        )
        return estimate
