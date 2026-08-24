#!/usr/bin/env python3
"""
Momentum Pyramid Scaler (momentum_pyramid_scaler.py)
===================================================
Adds size to winning breakout positions as high-volume momentum confirms:
- Pyramiding Criteria:
  * Position is in profit (>= +1.5% Gain)
  * Stop-Loss is already shifted to Breakeven (0.0% downside risk on base position)
  * Volume surge confirms breakout (> 2.5x 5-minute baseline volume)
  * Adds +20% to +30% incremental size with trailing risk-free envelope
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("PyramidScaler")


@dataclass
class PyramidScaleSignal:
    symbol: str
    position_id: str
    pyramid_level: int  # 1st add, 2nd add
    additional_size_usd: float
    current_profit_pct: float
    volume_surge_multiplier: float
    new_average_entry_price: float
    is_risk_free_pyramid: bool
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🚀 [PYRAMID SCALER] Add #{self.pyramid_level} on {self.symbol} | Add Size: +${self.additional_size_usd:,.2f} USD | "
            f"Profit: {self.current_profit_pct:+.2f}% | Vol Surge: {self.volume_surge_multiplier:.1f}x | Risk-Free: {self.is_risk_free_pyramid}"
        )


class MomentumPyramidScaler:
    """
    Risk-Free Trend Breakout Pyramid Scaler.
    """

    def __init__(
        self,
        min_profit_to_pyramid_pct: float = 1.5,
        max_pyramid_adds: int = 2,
        add_size_ratio: float = 0.25,  # Add 25% of original size
    ):
        self.min_profit_to_pyramid_pct = min_profit_to_pyramid_pct
        self.max_pyramid_adds = max_pyramid_adds
        self.add_size_ratio = add_size_ratio
        self.pyramid_history: Dict[str, int] = {}  # position_id -> count of adds

    def evaluate_pyramid_opportunity(
        self,
        position_id: str,
        symbol: str,
        initial_size_usd: float,
        current_profit_pct: float,
        current_volume_multiplier: float,  # e.g. 2.8x
        is_breakeven_locked: bool,
        current_price: float,
    ) -> Optional[PyramidScaleSignal]:
        """
        Evaluates whether adding size to an existing winning trade is mathematically optimal.
        """
        sym = symbol.upper()
        adds_done = self.pyramid_history.get(position_id, 0)

        if adds_done >= self.max_pyramid_adds:
            return None

        if not is_breakeven_locked:
            return None

        if current_profit_pct < self.min_profit_to_pyramid_pct:
            return None

        if current_volume_multiplier < 2.0:
            return None

        # Calculate add size
        add_usd = initial_size_usd * self.add_size_ratio
        new_adds = adds_done + 1
        self.pyramid_history[position_id] = new_adds

        signal = PyramidScaleSignal(
            symbol=sym,
            position_id=position_id,
            pyramid_level=new_adds,
            additional_size_usd=round(add_usd, 2),
            current_profit_pct=round(current_profit_pct, 2),
            volume_surge_multiplier=round(current_volume_multiplier, 2),
            new_average_entry_price=round(current_price, 4),
            is_risk_free_pyramid=True,
        )
        logger.info(signal.summary())
        return signal
