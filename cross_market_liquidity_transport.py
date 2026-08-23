#!/usr/bin/env python3
"""
Cross-Market Liquidity Optimal Transport (cross_market_liquidity_transport.py)
=============================================================================
Calculates the 1-Wasserstein Earth Mover's Distance (EMD) between orderbook liquidity distributions
across zkLighter, Hyperliquid, and Binance:
  W_1(P, Q) = ∫_0^1 |F_P^{-1}(u) - F_Q^{-1}(u)| du

Key Capabilities:
- Quantifies the structural dissimilarity of depth profiles between CEX and DEX
- Detects when liquidity transport costs between venues are low, triggering cross-market arbitrage
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("LiquidityTransport")


@dataclass
class WassersteinTransportResult:
    source_venue: str
    target_venue: str
    symbol: str
    wasserstein_distance_usd: float
    relative_transport_cost_bps: float
    is_arbitrage_profitable: bool
    arbitrage_edge_bps: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🌊 [WASSERSTEIN TRANSPORT] {self.source_venue} ➡️ {self.target_venue} on {self.symbol} | "
            f"EMD: ${self.wasserstein_distance_usd:,.2f} (Transport Cost: {self.relative_transport_cost_bps:.2f} bps) | "
            f"Arb Profitable: {self.is_arbitrage_profitable} (Edge: +{self.arbitrage_edge_bps:.2f} bps)"
        )


class CrossMarketLiquidityTransportEngine:
    """
    Wasserstein Optimal Transport Liquidity Distance Estimator.
    """

    def compute_wasserstein_distance(
        self,
        source_venue: str,
        target_venue: str,
        symbol: str,
        source_depth_profile: List[float],  # Depth per price bin
        target_depth_profile: List[float],
        mid_price: float,
    ) -> WassersteinTransportResult:
        """
        Calculates 1-Wasserstein distance between two liquidity density distributions.
        """
        sym = symbol.upper()
        s_ven = source_venue.upper()
        t_ven = target_venue.upper()

        if not source_depth_profile or not target_depth_profile:
            return WassersteinTransportResult(
                source_venue=s_ven,
                target_venue=t_ven,
                symbol=sym,
                wasserstein_distance_usd=0.0,
                relative_transport_cost_bps=0.0,
                is_arbitrage_profitable=False,
                arbitrage_edge_bps=0.0,
            )

        # Normalize profiles to probability mass
        tot_s = sum(source_depth_profile) or 1.0
        tot_t = sum(target_depth_profile) or 1.0

        p_s = [d / tot_s for d in source_depth_profile]
        p_t = [d / tot_t for d in target_depth_profile]

        # Cumulative distribution functions
        cdf_s: List[float] = []
        cdf_t: List[float] = []
        cum_s = 0.0
        cum_t = 0.0

        n = max(len(p_s), len(p_t))
        for i in range(n):
            cum_s += p_s[i] if i < len(p_s) else 0.0
            cum_t += p_t[i] if i < len(p_t) else 0.0
            cdf_s.append(cum_s)
            cdf_t.append(cum_t)

        # Wasserstein Distance = sum |CDF_P - CDF_Q|
        emd = sum(abs(cdf_s[i] - cdf_t[i]) for i in range(n)) * 1000.0

        transport_cost_bps = (emd / max(100.0, mid_price)) * 0.10
        raw_spread_bps = abs(tot_s - tot_t) / max(1.0, tot_s) * 5.0
        edge_bps = max(0.0, raw_spread_bps - transport_cost_bps)

        is_arb = edge_bps >= 2.0

        res = WassersteinTransportResult(
            source_venue=s_ven,
            target_venue=t_ven,
            symbol=sym,
            wasserstein_distance_usd=round(emd, 2),
            relative_transport_cost_bps=round(transport_cost_bps, 2),
            is_arbitrage_profitable=is_arb,
            arbitrage_edge_bps=round(edge_bps, 2),
        )
        return res
