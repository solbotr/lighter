#!/usr/bin/env python3
"""
Continuous Inventory Convexity Skew (inventory_convexity_skew.py)
================================================================
Implements non-linear polynomial inventory risk penalties:
  Penalty: Π(q) = -φ · q² - ψ · q³

Key Capabilities:
- As inventory q grows toward the hard cap, quote skewing steepens exponentially
- Eliminates inventory accumulation in runaway trend markets by rapidly widening the accumulating side
  and pulling the offloading quote aggressively inside the orderbook spread
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("InventoryConvexity")


@dataclass
class ConvexitySkewResult:
    symbol: str
    current_inventory_usd: float
    max_position_limit_usd: float
    inventory_utilization_pct: float
    linear_skew_bps: float
    convex_penalty_bps: float
    total_quote_offset_bps: float
    recommended_bid_offset_bps: float
    recommended_ask_offset_bps: float
    is_emergency_offload_active: bool
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"⚖️ [CONVEXITY SKEW] {self.symbol} | Inventory: ${self.current_inventory_usd:,.2f}/${self.max_position_limit_usd:,.2f} ({self.inventory_utilization_pct:.1f}%) | "
            f"Convex Penalty: +{self.convex_penalty_bps:.1f} bps (Total Offset: {self.total_quote_offset_bps:+.1f} bps) | "
            f"Emergency Offload: {self.is_emergency_offload_active}"
        )


class InventoryConvexitySkewEngine:
    """
    Non-Linear Convex Inventory Risk Controller.
    """

    def __init__(
        self,
        max_position_limit_usd: float = 200.0,
        quadratic_phi: float = 0.05,
        cubic_psi: float = 0.02,
    ):
        self.max_position_limit_usd = max_position_limit_usd
        self.quadratic_phi = quadratic_phi
        self.cubic_psi = cubic_psi

    def compute_convex_quote_skew(
        self,
        symbol: str,
        current_inventory_usd: float,
        base_half_spread_bps: float = 5.0,
    ) -> ConvexitySkewResult:
        """
        Calculates non-linear convex inventory offsets for bid and ask quotes.
        """
        sym = symbol.upper()
        cap = self.max_position_limit_usd
        inv = current_inventory_usd

        # Normalized inventory ratio q in [-1.0, 1.0]
        q_ratio = max(-1.0, min(1.0, inv / cap)) if cap > 0 else 0.0
        util_pct = abs(q_ratio) * 100.0

        # Linear component: -q * base_spread
        lin_bps = -q_ratio * base_half_spread_bps * 1.5

        # Non-linear convex penalty: -sign(q) * (φ * q² + ψ * |q|³) * 10.0
        sign_q = 1.0 if q_ratio >= 0 else -1.0
        convex_bps = sign_q * (self.quadratic_phi * (q_ratio ** 2) + self.cubic_psi * (abs(q_ratio) ** 3)) * 100.0

        total_offset = lin_bps - (sign_q * convex_bps)
        is_emerg = util_pct >= 85.0

        # When Long (q > 0): Push Ask tighter (lower price to sell), widen Bid (lower price to prevent buying)
        # When Short (q < 0): Push Bid tighter (higher price to buy), widen Ask (higher price to prevent selling)
        if q_ratio > 0:
            rec_bid_offset = -base_half_spread_bps - abs(total_offset)
            rec_ask_offset = max(1.0, base_half_spread_bps - abs(total_offset) * 0.5)
        elif q_ratio < 0:
            rec_bid_offset = -max(1.0, base_half_spread_bps - abs(total_offset) * 0.5)
            rec_ask_offset = base_half_spread_bps + abs(total_offset)
        else:
            rec_bid_offset = -base_half_spread_bps
            rec_ask_offset = base_half_spread_bps

        result = ConvexitySkewResult(
            symbol=sym,
            current_inventory_usd=round(inv, 2),
            max_position_limit_usd=round(cap, 2),
            inventory_utilization_pct=round(util_pct, 1),
            linear_skew_bps=round(lin_bps, 2),
            convex_penalty_bps=round(convex_bps, 2),
            total_quote_offset_bps=round(total_offset, 2),
            recommended_bid_offset_bps=round(rec_bid_offset, 2),
            recommended_ask_offset_bps=round(rec_ask_offset, 2),
            is_emergency_offload_active=is_emerg,
        )
        return result
