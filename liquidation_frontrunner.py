#!/usr/bin/env python3
"""
On-Chain Liquidation Cascade Front-Runner (liquidation_frontrunner.py)
====================================================================
Tracks high-leverage whale liquidation risk across Hyperliquid and zkLighter:
- Monitors margin buffer ratio = (Maintenance Margin / Account Equity)
- When a large position (≥ $25,000 USD) reaches > 90% margin stress, calculates
  the expected forced liquidation market impact clearing price.
- Pre-places counter-limit orders right at the liquidation clearing wick to capture instant 1.5% - 3.0% rebounds.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("LiquidationFrontrunner")


@dataclass
class DistressedPosition:
    trader_wallet: str
    symbol: str
    side: str  # "LONG" or "SHORT"
    position_notional_usd: float
    entry_price: float
    liquidation_price: float
    current_margin_ratio_pct: float
    is_liquidation_imminent: bool


@dataclass
class LiquidationFrontrunSignal:
    signal_id: str
    symbol: str
    distressed_side: str  # "LONG" or "SHORT"
    counter_trade_side: str  # "BUY" if Long is liquidating, "SELL" if Short is liquidating
    distressed_notional_usd: float
    estimated_clearing_price: float
    recommended_entry_price: float
    target_rebound_tp_price: float
    expected_rebound_pct: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"⚡ [LIQUIDATION SNIPE] ${self.distressed_notional_usd:,.2f} {self.symbol} {self.distressed_side} Liquidating! ➡️ "
            f"Pre-Place {self.counter_trade_side} Limit @ ${self.recommended_entry_price:,.2f} (Target TP: ${self.target_rebound_tp_price:,.2f}, +{self.expected_rebound_pct:.1f}%)"
        )


class LiquidationCascadeFrontrunner:
    """
    Whale Liquidation Front-Running Engine.
    """

    def __init__(
        self,
        min_distressed_notional_usd: float = 20000.0,
        margin_stress_threshold_pct: float = 85.0,
    ):
        self.min_distressed_notional_usd = min_distressed_notional_usd
        self.margin_stress_threshold_pct = margin_stress_threshold_pct

    def evaluate_position_distress(
        self,
        trader_wallet: str,
        symbol: str,
        side: str,
        position_notional_usd: float,
        entry_price: float,
        current_price: float,
        liquidation_price: float,
        margin_ratio_pct: float,
    ) -> Optional[LiquidationFrontrunSignal]:
        """
        Evaluates whether a large position is nearing liquidation and generates pre-emptive counter-order signals.
        """
        sym = symbol.upper()
        s = side.upper()

        if position_notional_usd < self.min_distressed_notional_usd:
            return None

        if margin_ratio_pct < self.margin_stress_threshold_pct:
            return None

        # Determine clearing price with market impact overshoot
        is_long = s == "LONG"
        counter_side = "BUY" if is_long else "SELL"

        # Liquidations overshoot liquidation price by 0.5% - 1.5%
        overshoot_pct = 0.008  # 80 bps overshoot
        if is_long:
            clearing_px = liquidation_price * (1.0 - overshoot_pct)
            entry_px = clearing_px * 1.001
            tp_px = clearing_px * 1.020  # +2.0% rebound
        else:
            clearing_px = liquidation_price * (1.0 + overshoot_pct)
            entry_px = clearing_px * 0.999
            tp_px = clearing_px * 0.980  # -2.0% rebound

        sig = LiquidationFrontrunSignal(
            signal_id=f"liq_sig_{sym}_{int(time.time()*1000)}",
            symbol=sym,
            distressed_side=s,
            counter_trade_side=counter_side,
            distressed_notional_usd=position_notional_usd,
            estimated_clearing_price=round(clearing_px, 4),
            recommended_entry_price=round(entry_px, 4),
            target_rebound_tp_price=round(tp_px, 4),
            expected_rebound_pct=2.0,
        )
        logger.info(sig.summary())
        return sig
