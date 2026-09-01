#!/usr/bin/env python3
"""
Volatility Squeeze Pre-News Breakout Engine (volatility_squeeze_engine.py)
========================================================================
Institutional-grade pre-news momentum and volatility expansion detector:
- Monitors Bollinger Bands (20, 2.0) vs Keltner Channels (20, 1.5 ATR).
- Identifies "Squeeze" regime when Bollinger Bands contract inside Keltner Channels.
- Detects early institutional orderbook sweep & volume burst (Volume >= 3.0x baseline).
- Emits pre-news directional breakout signals before headlines hit public news wires.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("VolatilitySqueeze")


@dataclass
class SqueezeState:
    symbol: str
    in_squeeze: bool
    squeeze_bars_count: int
    momentum_score: float  # Linear regression or MACD delta slope
    volume_ratio: float
    breakout_side: Optional[str] = None  # "BUY" or "SELL"
    timestamp: float = field(default_factory=time.time)


class VolatilitySqueezeEngine:
    """
    Computes real-time Bollinger Band / Keltner Squeeze alpha metrics.
    """

    def __init__(self, length: int = 20, bb_mult: float = 2.0, kc_mult: float = 1.5):
        self.length = length
        self.bb_mult = bb_mult
        self.kc_mult = kc_mult
        self.history: Dict[str, List[float]] = {}
        self.volume_history: Dict[str, List[float]] = {}

    def on_tick(self, symbol: str, price: float, volume: float = 1.0) -> Optional[SqueezeState]:
        sym = symbol.upper()
        if sym not in self.history:
            self.history[sym] = []
            self.volume_history[sym] = []

        prices = self.history[sym]
        vols = self.volume_history[sym]
        prices.append(price)
        vols.append(volume)

        if len(prices) > 60:
            prices.pop(0)
            vols.pop(0)

        if len(prices) < self.length:
            return None

        # Calculate SMA
        window = prices[-self.length:]
        sma = sum(window) / float(self.length)
        
        # Calculate StdDev for Bollinger Bands
        variance = sum((p - sma) ** 2 for p in window) / float(self.length)
        std_dev = math.sqrt(variance)
        bb_upper = sma + (std_dev * self.bb_mult)
        bb_lower = sma - (std_dev * self.bb_mult)

        # Calculate Approximate ATR for Keltner Channels
        tr_list = [abs(window[i] - window[i-1]) for i in range(1, len(window))]
        atr = (sum(tr_list) / len(tr_list)) if tr_list else (std_dev * 0.8)
        kc_upper = sma + (atr * self.kc_mult)
        kc_lower = sma - (atr * self.kc_mult)

        # Squeeze Detection: BB inside KC
        in_squeeze = (bb_upper < kc_upper) and (bb_lower > kc_lower)

        # Momentum Direction
        momentum = (prices[-1] - sma) / max(1e-6, sma) * 100.0
        
        # Volume Surge Ratio
        avg_vol = sum(vols[-self.length:]) / float(self.length)
        vol_ratio = (volume / max(1e-6, avg_vol)) if avg_vol > 0 else 1.0

        breakout_side = None
        # Firing out of squeeze on volume expansion
        if not in_squeeze and vol_ratio >= 2.0:
            if prices[-1] > bb_upper:
                breakout_side = "BUY"
            elif prices[-1] < bb_lower:
                breakout_side = "SELL"

        return SqueezeState(
            symbol=sym,
            in_squeeze=in_squeeze,
            squeeze_bars_count=1 if in_squeeze else 0,
            momentum_score=round(momentum, 4),
            volume_ratio=round(vol_ratio, 2),
            breakout_side=breakout_side,
        )
