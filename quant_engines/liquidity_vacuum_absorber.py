#!/usr/bin/env python3
"""
Orderbook Liquidity Vacuum Magnet & Pocket Absorber (liquidity_vacuum_absorber.py)
==================================================================================
Identifies low-density "air pockets" across L2/L3 orderbook depth:
- Detects price zones where resting depth is < 15% of average level thickness
- Predicts price acceleration gliding through the vacuum toward the opposing liquidity shelf
- Pre-places sniper limit orders directly at the shelf boundary to absorb maximum fill momentum
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("VacuumAbsorber")


@dataclass
class OrderbookDepthLevel:
    price: float
    depth_usd: float


@dataclass
class LiquidityVacuumZone:
    symbol: str
    side: str  # "ASK_VACUUM" (Bullish Price Glide) or "BID_VACUUM" (Bearish Price Glide)
    vacuum_start_price: float
    vacuum_end_price: float
    shelf_target_price: float
    vacuum_thickness_usd: float
    average_level_thickness_usd: float
    vacuum_density_ratio: float  # e.g. 0.08 (8% of normal depth)
    expected_glide_speed_ms: float
    is_actionable: bool
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🌊 [LIQUIDITY VACUUM] {self.symbol} {self.side} | Air Pocket: ${self.vacuum_start_price:,.2f} ➡️ ${self.vacuum_end_price:,.2f} | "
            f"Shelf Target: ${self.shelf_target_price:,.2f} | Density: {self.vacuum_density_ratio*100:.1f}% of normal | Glide Speed: ~{self.expected_glide_speed_ms:.0f}ms"
        )


class LiquidityVacuumAbsorberEngine:
    """
    Orderbook Air-Pocket & Liquidity Shelf Targeter.
    """

    def __init__(self, vacuum_threshold_pct: float = 20.0, min_vacuum_span_bps: float = 15.0):
        self.vacuum_threshold_pct = vacuum_threshold_pct
        self.min_vacuum_span_bps = min_vacuum_span_bps

    def scan_orderbook_for_vacuums(
        self,
        symbol: str,
        side: str,  # "ASK" or "BID"
        levels: List[OrderbookDepthLevel],
    ) -> Optional[LiquidityVacuumZone]:
        """
        Scans depth levels to detect air pockets and target the opposing liquidity shelf.
        """
        sym = symbol.upper()
        s = side.upper()

        if len(levels) < 5:
            return None

        avg_depth = sum(l.depth_usd for l in levels) / len(levels)
        if avg_depth <= 0:
            return None

        # Identify contiguous thin levels
        thin_levels: List[OrderbookDepthLevel] = []
        shelf_level: Optional[OrderbookDepthLevel] = None

        for lvl in levels:
            if lvl.depth_usd <= (avg_depth * (self.vacuum_threshold_pct / 100.0)):
                thin_levels.append(lvl)
            else:
                if thin_levels and lvl.depth_usd >= (avg_depth * 1.5):
                    shelf_level = lvl
                    break

        if len(thin_levels) >= 2 and shelf_level is not None:
            start_px = thin_levels[0].price
            end_px = thin_levels[-1].price
            span_bps = abs(end_px - start_px) / start_px * 10000.0

            if span_bps >= self.min_vacuum_span_bps:
                tot_vac_depth = sum(l.depth_usd for l in thin_levels)
                density_ratio = (tot_vac_depth / (len(thin_levels) * avg_depth))

                vac_side = "ASK_VACUUM" if s == "ASK" else "BID_VACUUM"
                glide_ms = len(thin_levels) * 35.0  # Approx 35ms per thin tick level

                zone = LiquidityVacuumZone(
                    symbol=sym,
                    side=vac_side,
                    vacuum_start_price=round(start_px, 4),
                    vacuum_end_price=round(end_px, 4),
                    shelf_target_price=round(shelf_level.price, 4),
                    vacuum_thickness_usd=round(tot_vac_depth, 2),
                    average_level_thickness_usd=round(avg_depth, 2),
                    vacuum_density_ratio=round(density_ratio, 3),
                    expected_glide_speed_ms=round(glide_ms, 1),
                    is_actionable=True,
                )
                logger.info(zone.summary())
                return zone

        return None
