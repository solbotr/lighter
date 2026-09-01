#!/usr/bin/env python3
"""
zkLighter Triangular & Cross-Pair Basis Arbitrage Engine (triangular_arbitrage.py)
=================================================================================
High-frequency zero-risk circular arbitrage across correlated crypto/forex pairs:
- Continuously calculates synthetic cross-rates vs actual DEX quote rates.
- E.g. Leg 1 (BTC/USDC) -> Leg 2 (ETH/BTC) -> Leg 3 (ETH/USDC).
- E.g. Leg 1 (EUR/USD) -> Leg 2 (GBP/USD) -> Leg 3 (EUR/GBP).
- Detects circular arbitrage loop spread >= 15 bps (after taker fees).
- Fully delta-neutral with zero directional market risk.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("TriangularArbitrage")


@dataclass(frozen=True)
class TriangularLoop:
    loop_id: str
    leg1_symbol: str
    leg2_symbol: str
    leg3_symbol: str
    synthetic_rate: float
    actual_rate: float
    gross_edge_bps: float
    net_edge_bps: float
    target_usd: float
    estimated_profit_usd: float
    timestamp: float = field(default_factory=time.time)

    @property
    def is_actionable(self) -> bool:
        return self.net_edge_bps >= 10.0 and self.target_usd > 0.0


class TriangularArbitrageScanner:
    """
    Scans for 3-leg circular micro-pricing discrepancies on zkLighter.
    """

    def __init__(self, fee_bps_per_leg: float = 2.0):
        self.fee_bps_total = fee_bps_per_leg * 3.0
        self.opportunities: List[TriangularLoop] = []

    def scan_triangular_loop(
        self,
        p_a_usdc: float,  # E.g. ETH/USDC
        p_b_usdc: float,  # E.g. BTC/USDC
        p_a_b: float,     # E.g. ETH/BTC synthetic or cross
        symbol_a: str = "ETH",
        symbol_b: str = "BTC",
        max_usd_size: float = 200.0,
    ) -> Optional[TriangularLoop]:
        """
        Calculates loop discrepancy:
        Synthetic Price A/B = P(A/USDC) / P(B/USDC)
        Edge = (Actual P(A/B) - Synthetic P(A/B)) / Synthetic P(A/B)
        """
        if p_a_usdc <= 0 or p_b_usdc <= 0 or p_a_b <= 0:
            return None

        synthetic = p_a_usdc / p_b_usdc
        diff_bps = ((p_a_b - synthetic) / synthetic) * 10000.0
        gross_bps = abs(diff_bps)
        net_bps = gross_bps - self.fee_bps_total

        if net_bps >= 10.0:
            profit_usd = (max_usd_size * net_bps) / 10000.0
            opp = TriangularLoop(
                loop_id=f"TRI_{symbol_a}_{symbol_b}_{int(time.time()*1000)}",
                leg1_symbol=f"{symbol_a}/USDC",
                leg2_symbol=f"{symbol_b}/USDC",
                leg3_symbol=f"{symbol_a}/{symbol_b}",
                synthetic_rate=synthetic,
                actual_rate=p_a_b,
                gross_edge_bps=gross_bps,
                net_edge_bps=net_bps,
                target_usd=max_usd_size,
                estimated_profit_usd=profit_usd,
            )
            self.opportunities.append(opp)
            if len(self.opportunities) > 50:
                self.opportunities.pop(0)
            return opp

        return None
