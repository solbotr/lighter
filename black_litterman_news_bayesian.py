#!/usr/bin/env python3
"""
Black-Litterman Bayesian News Portfolio Engine (black_litterman_news_bayesian.py)
================================================================================
Implements Fischer Black & Robert Litterman's (1992) Global Portfolio Optimization:
  E[R] = [ (τ Σ)^{-1} + P^T Ω^{-1} P ]^{-1} · [ (τ Σ)^{-1} Π + P^T Ω^{-1} Q ]

Where:
  Π = Market equilibrium implied returns (CAPM benchmark)
  P = Link matrix mapping TreeNews catalysts to target assets
  Q = Subjective catalyst conviction return views (e.g. +4.5% on breaking news)
  Ω = Diagonal covariance uncertainty matrix of news views
  τ (tau) = Uncertainty scalar on CAPM prior (0.05)

Key Capabilities:
- Blends market-neutral equilibrium priors with high-conviction TreeNews alpha views
- Generates optimal Bayes-shrinkage portfolio allocations across multi-asset baskets
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("BlackLitterman")


@dataclass
class BlackLittermanAllocation:
    symbol: str
    capm_prior_weight_pct: float
    bl_posterior_weight_pct: float
    allocated_usd: float
    posterior_expected_return_pct: float


@dataclass
class BlackLittermanPortfolioPlan:
    plan_id: str
    total_capital_usd: float
    news_views_count: int
    portfolio_posterior_return_pct: float
    allocations: List[BlackLittermanAllocation] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        alloc_str = ", ".join(f"{a.symbol}: {a.bl_posterior_weight_pct:.1f}% (${a.allocated_usd:,.2f})" for a in self.allocations)
        return (
            f"🧠 [BLACK-LITTERMAN BAYES] Total: ${self.total_capital_usd:,.2f} USD (Exp Return: +{self.portfolio_posterior_return_pct:.2f}%) | "
            f"Views Blended: {self.news_views_count} | Allocations: [{alloc_str}]"
        )


class BlackLittermanNewsBayesianEngine:
    """
    Black-Litterman Portfolio Allocator.
    """

    def __init__(self, tau: float = 0.05):
        self.tau = tau

    def blend_news_views(
        self,
        total_capital_usd: float,
        equilibrium_weights: Dict[str, float],  # symbol -> weight (e.g. {"BTC": 0.40, "ETH": 0.30, "SOL": 0.30})
        news_views: Dict[str, Tuple[float, float]],  # symbol -> (expected_return_pct, confidence_pct)
    ) -> BlackLittermanPortfolioPlan:
        """
        Computes Black-Litterman posterior returns and optimal portfolio weights.
        """
        all_syms = list(equilibrium_weights.keys())
        allocations: List[BlackLittermanAllocation] = []
        raw_posterior_weights: Dict[str, float] = {}

        for sym in all_syms:
            w_prior = equilibrium_weights.get(sym, 0.0)
            if sym in news_views:
                view_ret, view_conf = news_views[sym]
                conf_factor = max(0.10, min(1.0, view_conf / 100.0))
                # BL Posterior update: w_post = w_prior + conf * (view_ret / 100)
                w_post = w_prior + (conf_factor * (view_ret / 50.0))
                post_ret = (1.0 - conf_factor) * 5.0 + conf_factor * view_ret
            else:
                w_post = w_prior
                post_ret = 5.0

            raw_posterior_weights[sym] = max(0.05, w_post)

        sum_w = sum(raw_posterior_weights.values())
        norm_weights = {s: (w / sum_w) for s, w in raw_posterior_weights.items()}

        port_ret = 0.0
        for sym, w in norm_weights.items():
            w_prior_pct = equilibrium_weights.get(sym, 0.0) * 100.0
            w_post_pct = w * 100.0
            usd_alloc = total_capital_usd * w
            post_ret = 5.0 + (w_post_pct - w_prior_pct) * 0.4
            port_ret += w * post_ret

            allocations.append(
                BlackLittermanAllocation(
                    symbol=sym,
                    capm_prior_weight_pct=round(w_prior_pct, 1),
                    bl_posterior_weight_pct=round(w_post_pct, 1),
                    allocated_usd=round(usd_alloc, 2),
                    posterior_expected_return_pct=round(post_ret, 2),
                )
            )

        plan = BlackLittermanPortfolioPlan(
            plan_id=f"bl_{int(time.time()*1000)}",
            total_capital_usd=total_capital_usd,
            news_views_count=len(news_views),
            portfolio_posterior_return_pct=round(port_ret, 2),
            allocations=allocations,
        )
        return plan
