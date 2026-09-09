#!/usr/bin/env python3
"""
Catalyst Anchored-VWAP & Volume Profile POC Magnet (anchored_vwap_profile.py)
=============================================================================
Calculates high-precision Volume Profile and Anchored VWAP anchored to news events:
- Anchored VWAP = ∑(Price · Volume) / ∑(Volume) from anchor timestamp
- Point of Control (POC): Price level with maximum accumulated volume
- Low-Volume Nodes (LVN): Liquidity vacuums ideal for setting sharp Take-Profit limit exits
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AnchoredVWAP")


@dataclass
class VolumeProfileNode:
    price_level: float
    total_volume_usd: float
    is_poc: bool = False
    is_lvn: bool = False


@dataclass
class AnchoredProfileResult:
    symbol: str
    anchor_timestamp: float
    anchored_vwap: float
    point_of_control_price: float
    upper_value_area: float  # VAH (70% Volume Area High)
    lower_value_area: float  # VAL (70% Volume Area Low)
    target_lvn_exit: float   # Optimal Take-Profit target
    total_anchored_volume_usd: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"📊 [ANCHORED VWAP] {self.symbol} | aVWAP: ${self.anchored_vwap:,.2f} | POC: ${self.point_of_control_price:,.2f} | "
            f"VAH: ${self.upper_value_area:,.2f} / VAL: ${self.lower_value_area:,.2f} | Target LVN: ${self.target_lvn_exit:,.2f} | "
            f"Anchored Vol: ${self.total_anchored_volume_usd:,.2f}"
        )


class AnchoredVWAPProfileEngine:
    """
    Computes Event-Anchored VWAP and Value Area Distributions.
    """

    def __init__(self, price_bin_size_pct: float = 0.001):  # 10 bps price bins
        self.price_bin_size_pct = price_bin_size_pct
        self.anchor_ticks: Dict[str, List[Tuple[float, float, float]]] = {}  # (price, vol, timestamp)

    def set_catalyst_anchor(self, symbol: str, anchor_timestamp: Optional[float] = None) -> None:
        """Sets a new anchor event timestamp, clearing prior session history."""
        sym = symbol.upper()
        self.anchor_ticks[sym] = []

    def push_tick(self, symbol: str, price: float, volume_usd: float, timestamp: Optional[float] = None) -> None:
        """Appends trade tick to active anchored session."""
        sym = symbol.upper()
        if sym not in self.anchor_ticks:
            self.anchor_ticks[sym] = []
        now = timestamp or time.time()
        self.anchor_ticks[sym].append((price, volume_usd, now))

    def compute_anchored_profile(self, symbol: str, current_price: float, direction: str = "BUY") -> AnchoredProfileResult:
        """
        Calculates Anchored VWAP, Point of Control (POC), and Liquidity Vacuum LVN.
        """
        sym = symbol.upper()
        ticks = self.anchor_ticks.get(sym, [])

        if not ticks:
            return AnchoredProfileResult(
                symbol=sym,
                anchor_timestamp=time.time(),
                anchored_vwap=current_price,
                point_of_control_price=current_price,
                upper_value_area=current_price * 1.015,
                lower_value_area=current_price * 0.985,
                target_lvn_exit=current_price * (1.025 if direction == "BUY" else 0.975),
                total_anchored_volume_usd=0.0,
            )

        sum_pv = sum(p * v for p, v, _ in ticks)
        total_v = sum(v for _, v, _ in ticks)
        avwap = sum_pv / total_v if total_v > 0 else current_price

        # Build Volume Profile histogram
        bins: Dict[float, float] = defaultdict(float)
        for p, v, _ in ticks:
            bin_px = round(p / (current_price * self.price_bin_size_pct)) * (current_price * self.price_bin_size_pct)
            bins[bin_px] += v

        # Find POC (Highest Volume Bin)
        poc_px = max(bins.keys(), key=lambda k: bins[k]) if bins else current_price

        # Compute Value Area (70% Volume bounds)
        sorted_bins = sorted(bins.items(), key=lambda x: x[0])
        target_vol = total_v * 0.70
        accum_vol = 0.0
        vah = current_price * 1.01
        val = current_price * 0.99

        for p_val, v_amt in sorted_bins:
            accum_vol += v_amt
            if accum_vol >= total_v * 0.15 and val == current_price * 0.99:
                val = p_val
            if accum_vol >= target_vol:
                vah = p_val
                break

        # Find nearest LVN (Low Volume Node) above current price for Long, below for Short
        if direction.upper() in ("BUY", "LONG"):
            higher_bins = [p for p, v in bins.items() if p > current_price]
            target_lvn = min(higher_bins, key=lambda p: bins[p]) if higher_bins else current_price * 1.03
        else:
            lower_bins = [p for p, v in bins.items() if p < current_price]
            target_lvn = min(lower_bins, key=lambda p: bins[p]) if lower_bins else current_price * 0.97

        result = AnchoredProfileResult(
            symbol=sym,
            anchor_timestamp=ticks[0][2] if ticks else time.time(),
            anchored_vwap=round(avwap, 4),
            point_of_control_price=round(poc_px, 4),
            upper_value_area=round(vah, 4),
            lower_value_area=round(val, 4),
            target_lvn_exit=round(target_lvn, 4),
            total_anchored_volume_usd=round(total_v, 2),
        )
        return result
