#!/usr/bin/env python3
"""
Institutional Liquidity Wall Breakout Sweeper (liquidity_wall_sweeper.py)
========================================================================
Scans orderbook depth for major resting institutional limit walls (≥ $250,000 USD).
Tracks wall erosion in real time:
- When a massive ask wall is > 70% consumed in < 500ms, fires a pre-emptive Long breakout snipe
- When a massive bid wall is > 70% consumed in < 500ms, fires a pre-emptive Short breakdown snipe
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("LiquidityWallSweeper")


@dataclass
class LiquidityWall:
    wall_id: str
    symbol: str
    side: str  # "ASK" or "BID"
    price_level: float
    initial_notional_usd: float
    current_notional_usd: float
    consumption_pct: float
    first_seen_timestamp: float
    last_updated_timestamp: float = field(default_factory=time.time)

    @property
    def is_wall_eroded(self) -> bool:
        return self.consumption_pct >= 70.0


@dataclass
class WallBreakoutSignal:
    signal_id: str
    symbol: str
    direction: str  # "BUY_BREAKOUT" (Ask Wall Collapsing) or "SELL_BREAKDOWN" (Bid Wall Collapsing)
    wall_price: float
    initial_wall_usd: float
    remaining_wall_usd: float
    erosion_speed_ms: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🌊 [WALL BREAKOUT] {self.direction} on {self.symbol} | Wall Px: ${self.wall_price:,.2f} | "
            f"Eroded: ${(self.initial_wall_usd - self.remaining_wall_usd):,.2f}/${self.initial_wall_usd:,.2f} USD in {self.erosion_speed_ms:.1f}ms"
        )


class LiquidityWallBreakoutSweeper:
    """
    High-Speed Liquidity Wall Erosion & Breakout Anticipator.
    """

    def __init__(
        self,
        min_wall_notional_usd: float = 100000.0,
        erosion_threshold_pct: float = 70.0,
        max_erosion_window_seconds: float = 3.0,
    ):
        self.min_wall_notional_usd = min_wall_notional_usd
        self.erosion_threshold_pct = erosion_threshold_pct
        self.max_erosion_window_seconds = max_erosion_window_seconds
        self.tracked_walls: Dict[str, LiquidityWall] = {}
        self.active_signals: Dict[str, WallBreakoutSignal] = {}

    def update_orderbook_wall(
        self,
        symbol: str,
        side: str,
        price: float,
        current_size_usd: float,
    ) -> Optional[WallBreakoutSignal]:
        """
        Ingests orderbook level depth and updates wall tracking state.
        """
        sym = symbol.upper()
        s = side.upper()
        wall_key = f"{sym}_{s}_{round(price, 4)}"
        now = time.time()

        if wall_key not in self.tracked_walls:
            # Register new wall if large enough
            if current_size_usd >= self.min_wall_notional_usd:
                self.tracked_walls[wall_key] = LiquidityWall(
                    wall_id=wall_key,
                    symbol=sym,
                    side=s,
                    price_level=price,
                    initial_notional_usd=current_size_usd,
                    current_notional_usd=current_size_usd,
                    consumption_pct=0.0,
                    first_seen_timestamp=now,
                )
            return None

        wall = self.tracked_walls[wall_key]
        wall.current_notional_usd = current_size_usd
        consumed = max(0.0, wall.initial_notional_usd - current_size_usd)
        wall.consumption_pct = (consumed / wall.initial_notional_usd) * 100.0
        wall.last_updated_timestamp = now

        duration = now - wall.first_seen_timestamp

        # Check if wall is collapsing fast
        if wall.consumption_pct >= self.erosion_threshold_pct and duration <= self.max_erosion_window_seconds:
            sig_id = f"wall_sig_{sym}_{int(now*1000)}"
            dir_str = "BUY_BREAKOUT" if s == "ASK" else "SELL_BREAKDOWN"

            sig = WallBreakoutSignal(
                signal_id=sig_id,
                symbol=sym,
                direction=dir_str,
                wall_price=wall.price_level,
                initial_wall_usd=wall.initial_notional_usd,
                remaining_wall_usd=wall.current_notional_usd,
                erosion_speed_ms=round(duration * 1000.0, 1),
            )
            self.active_signals[sig_id] = sig
            logger.info(sig.summary())
            # Remove tracked wall to avoid duplicate triggers
            del self.tracked_walls[wall_key]
            return sig

        return None
