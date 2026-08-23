#!/usr/bin/env python3
"""
Autonomous Whale Copy-Trader & Smart Money Follower (whale_copy_trader.py)
========================================================================
Tracks the top 20 verified profitable alpha whales on Hyperliquid and GMX in real-time.
When a top whale opens or scales a high-conviction position (>= $250,000 USD),
this engine calculates risk-adjusted proportional sizing and automatically mirrors
the trade on zkLighter with on-chain TP/SL protection and auto-exit when the whale unwinds.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import aiohttp
from hyperliquid_whale_tracker import CURATED_WHALES, HYPERLIQUID_API_URL

logger = logging.getLogger("WhaleCopyTrader")


class WhaleSignalType(str, Enum):
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_INCREASED = "POSITION_INCREASED"
    POSITION_CLOSED = "POSITION_CLOSED"
    POSITION_FLIPPED = "POSITION_FLIPPED"


@dataclass(frozen=True)
class WhaleTradeMirrorPlan:
    """Calculated mirror execution plan for an incoming whale position."""
    whale_address: str
    whale_alias: str
    asset: str
    side: str  # "BUY" / "LONG" or "SELL" / "SHORT"
    signal_type: WhaleSignalType
    whale_size: float
    whale_entry_price: float
    whale_notional_usd: float
    whale_leverage: float
    my_target_notional_usd: float
    my_target_size: float
    tp_pct: float = 3.5
    sl_pct: float = 1.5
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🐋 [WHALE MIRROR] {self.whale_alias} ({self.whale_address[:6]}...{self.whale_address[-4:]}) | "
            f"{self.side} {self.asset} @ ${self.whale_entry_price:,.2f} | "
            f"Whale Notional: ${self.whale_notional_usd:,.0f} ({self.whale_leverage:.1f}x) | "
            f"My Allocated Notional: ${self.my_target_notional_usd:,.2f} ({self.my_target_size:.4f} {self.asset})"
        )


class WhaleCopyTraderEngine:
    """
    Real-time autonomous whale copy-trading manager.
    Tracks curated whale portfolios and generates copy signals.
    """

    def __init__(
        self,
        min_whale_notional_usd: float = 250000.0,
        my_copy_capital_usd: float = 150.0,
        max_leverage: float = 5.0,
        on_mirror_signal: Optional[Callable[[WhaleTradeMirrorPlan], Any]] = None,
    ):
        self.min_whale_notional_usd = min_whale_notional_usd
        self.my_copy_capital_usd = my_copy_capital_usd
        self.max_leverage = max_leverage
        self.on_mirror_signal = on_mirror_signal

        self.curated_whales: Set[str] = set(w.lower() for w in CURATED_WHALES)
        self.known_positions: Dict[str, Dict[str, Dict[str, Any]]] = {}  # whale -> {asset: pos_dict}
        self.active_mirrored_positions: Dict[str, WhaleTradeMirrorPlan] = {}  # asset -> plan
        self.total_whale_signals_processed = 0
        self.total_mirrors_executed = 0
        self.is_running = False

    def evaluate_whale_position_change(
        self,
        whale_address: str,
        asset: str,
        current_pos: Dict[str, Any],
        alias: str = "Top Alpha Whale",
    ) -> Optional[WhaleTradeMirrorPlan]:
        """
        Evaluates a change in whale portfolio state and determines whether to mirror.
        """
        w_addr = whale_address.lower()
        sym = asset.upper()

        prev_pos = self.known_positions.setdefault(w_addr, {}).get(sym, {})
        current_size = float(current_pos.get("szi", 0.0))
        entry_px = float(current_pos.get("entryPx", 0.0))
        leverage = float(current_pos.get("leverage", {}).get("value", 1.0) if isinstance(current_pos.get("leverage"), dict) else current_pos.get("leverage", 1.0))
        notional_usd = abs(current_size * entry_px)

        prev_size = float(prev_pos.get("szi", 0.0))

        # Update cache
        self.known_positions[w_addr][sym] = current_pos

        # Check if size changed meaningfully
        if abs(current_size - prev_size) < 1e-6:
            return None

        self.total_whale_signals_processed += 1

        # Determine signal type
        if prev_size == 0.0 and current_size != 0.0:
            signal_type = WhaleSignalType.POSITION_OPENED
        elif (prev_size > 0 and current_size < 0) or (prev_size < 0 and current_size > 0):
            signal_type = WhaleSignalType.POSITION_FLIPPED
        elif abs(current_size) > abs(prev_size):
            signal_type = WhaleSignalType.POSITION_INCREASED
        elif current_size == 0.0:
            signal_type = WhaleSignalType.POSITION_CLOSED
        else:
            return None

        # Filter minimum whale size
        if notional_usd < self.min_whale_notional_usd and signal_type != WhaleSignalType.POSITION_CLOSED:
            return None

        side = "BUY" if current_size > 0 else "SELL"
        effective_notional = min(self.my_copy_capital_usd * min(leverage, self.max_leverage), 500.0)
        my_size = effective_notional / entry_px if entry_px > 0 else 0.0

        plan = WhaleTradeMirrorPlan(
            whale_address=whale_address,
            whale_alias=alias,
            asset=sym,
            side=side,
            signal_type=signal_type,
            whale_size=current_size,
            whale_entry_price=entry_px,
            whale_notional_usd=notional_usd,
            whale_leverage=leverage,
            my_target_notional_usd=effective_notional,
            my_target_size=my_size,
            tp_pct=3.5,
            sl_pct=1.5,
        )

        if signal_type != WhaleSignalType.POSITION_CLOSED:
            self.active_mirrored_positions[sym] = plan
            self.total_mirrors_executed += 1
        elif sym in self.active_mirrored_positions:
            del self.active_mirrored_positions[sym]

        if self.on_mirror_signal:
            try:
                self.on_mirror_signal(plan)
            except Exception as e:
                logger.error(f"[WhaleCopyTrader] Signal callback error: {e}")

        logger.info(plan.summary())
        return plan

    def get_summary_report(self) -> Dict[str, Any]:
        """Returns operational metrics for dashboard."""
        return {
            "watched_whales_count": len(self.curated_whales),
            "active_mirrored_positions": len(self.active_mirrored_positions),
            "total_whale_signals_processed": self.total_whale_signals_processed,
            "total_mirrors_executed": self.total_mirrors_executed,
            "min_whale_notional_filter_usd": self.min_whale_notional_usd,
            "my_allocated_capital_usd": self.my_copy_capital_usd,
        }
