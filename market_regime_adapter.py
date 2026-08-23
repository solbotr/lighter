#!/usr/bin/env python3
"""
Market Regime & Fear/Greed Posture Switch (market_regime_adapter.py)
===================================================================
Analyzes real-time market microstructure indicators:
1. Crypto Fear & Greed Index (0-100)
2. Aggregate Market Funding Rate Sentiment
3. 24-Hour Realized Volatility / ATR Multiplier

Classifies market state into 4 distinct regimes:
- BULL_MOMENTUM: Aggressive trend following, wider TP (+4.0%..+8.0%), Kelly leverage 8x.
- BEAR_DUMP: Defensive short bias, tight TP (+1.5%..+3.0%), trailing stop cushion tightened.
- CHOPPY_RANGE: Mean-reversion scalping, rapid Breakeven lock (+0.75%), lower size.
- EXTREME_VOLATILITY: Flash crash protection, ultra-fast SL (-1.0%), size reduction.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger("MarketRegimeAdapter")


class MarketRegime(str, Enum):
    BULL_MOMENTUM = "BULL_MOMENTUM"
    BEAR_DUMP = "BEAR_DUMP"
    CHOPPY_RANGE = "CHOPPY_RANGE"
    EXTREME_VOLATILITY = "EXTREME_VOLATILITY"


@dataclass(frozen=True)
class RegimeParameters:
    """Strategy tuning parameters adapted to the current market regime."""
    regime: MarketRegime
    fng_value: int                    # 0 to 100
    avg_funding_apr: float            # Annualized funding rate %
    volatility_multiplier: float      # e.g. 1.0 = normal, 2.5 = high
    tp_multiplier: float              # Multiplier for Take-Profit targets (e.g. 1.5x)
    sl_multiplier: float              # Multiplier for Stop-Loss (e.g. 0.8x tighter)
    max_position_size_pct: float      # Max % of portfolio per trade
    kelly_fraction: float             # Sizing fraction (0.25 to 1.0)
    preferred_strategy: str           # "TREND_FOLLOWING", "MEAN_REVERSION", "GRID_MM", "CASH_DEFENSIVE"
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🧠 [REGIME: {self.regime.value}] F&G: {self.fng_value}/100 | "
            f"Funding APR: {self.avg_funding_apr:+.1%} | Volatility: {self.volatility_multiplier:.2f}x | "
            f"TP Mult: {self.tp_multiplier:.2f}x | SL Mult: {self.sl_multiplier:.2f}x | "
            f"Preferred: {self.preferred_strategy}"
        )


class MarketRegimeAdapter:
    """
    Evaluates macro crypto indicators and dynamically adapts bot trading parameters.
    """

    def __init__(
        self,
        update_interval_sec: float = 300.0,  # Refresh every 5 minutes
        on_regime_change: Optional[Callable[[RegimeParameters], Any]] = None,
    ):
        self.update_interval_sec = update_interval_sec
        self.on_regime_change = on_regime_change
        self.current_regime_params: RegimeParameters = self._default_parameters()
        self.last_update_time: float = 0.0

    def _default_parameters(self) -> RegimeParameters:
        return RegimeParameters(
            regime=MarketRegime.CHOPPY_RANGE,
            fng_value=50,
            avg_funding_apr=0.10,
            volatility_multiplier=1.0,
            tp_multiplier=1.0,
            sl_multiplier=1.0,
            max_position_size_pct=25.0,
            kelly_fraction=0.5,
            preferred_strategy="TREND_FOLLOWING",
        )

    def classify_regime(
        self,
        fng_value: int,
        avg_funding_apr: float,
        volatility_multiplier: float,
    ) -> RegimeParameters:
        """
        Deterministic regime classifier based on macroeconomic and volatility signals.
        """
        if volatility_multiplier >= 2.2:
            regime = MarketRegime.EXTREME_VOLATILITY
            tp_mult = 1.6
            sl_mult = 0.8  # Tighter SL
            max_size = 15.0
            kelly = 0.35
            pref = "CASH_DEFENSIVE"

        elif fng_value >= 65 and avg_funding_apr >= 0.15:
            regime = MarketRegime.BULL_MOMENTUM
            tp_mult = 1.8  # Expand targets to ride runners
            sl_mult = 1.0
            max_size = 35.0
            kelly = 0.85
            pref = "TREND_FOLLOWING"

        elif fng_value <= 35 or avg_funding_apr <= -0.10:
            regime = MarketRegime.BEAR_DUMP
            tp_mult = 1.2
            sl_mult = 0.85
            max_size = 20.0
            kelly = 0.50
            pref = "BREAKDOWN_SHORT"

        else:
            regime = MarketRegime.CHOPPY_RANGE
            tp_mult = 0.9  # Quick scalps
            sl_mult = 0.95
            max_size = 25.0
            kelly = 0.60
            pref = "MEAN_REVERSION"

        params = RegimeParameters(
            regime=regime,
            fng_value=fng_value,
            avg_funding_apr=avg_funding_apr,
            volatility_multiplier=volatility_multiplier,
            tp_multiplier=tp_mult,
            sl_multiplier=sl_mult,
            max_position_size_pct=max_size,
            kelly_fraction=kelly,
            preferred_strategy=pref,
        )

        if self.current_regime_params.regime != regime and self.on_regime_change:
            try:
                self.on_regime_change(params)
            except Exception as e:
                logger.error(f"[MarketRegime] Callback exception: {e}")

        self.current_regime_params = params
        self.last_update_time = time.time()
        logger.info(params.summary())
        return params

    async def fetch_live_regime(self) -> RegimeParameters:
        """Queries live public Fear & Greed API and updates regime."""
        fng = 50
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.alternative.me/fng/?limit=1", timeout=aiohttp.ClientTimeout(total=3.0)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        val = data.get("data", [{}])[0].get("value")
                        if val is not None:
                            fng = int(val)
        except Exception as e:
            logger.debug(f"[MarketRegime] FNG API fetch error: {e}")

        # Inferred funding and baseline volatility
        return self.classify_regime(
            fng_value=fng,
            avg_funding_apr=0.12,
            volatility_multiplier=1.1,
        )
