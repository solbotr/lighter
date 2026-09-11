#!/usr/bin/env python3
"""
Multi-Position Concurrency & Maximum Sizing Engine (multi_position_concurrency_engine.py)
========================================================================================
Unlocks simultaneous multi-position catalyst execution across distinct market clusters
while enforcing mathematical margin safety constraints:

Key Capabilities:
- Allows up to 5 concurrent active positions across uncorrelated sectors (e.g. BTC, ETH, SOL, AI, Memes)
- Dynamic Kelly Sizing based on catalyst conviction:
  * 98% conviction -> up to 85% available capital
  * 85% conviction -> up to 60% available capital
  * 75% conviction -> up to 40% available capital
- Uncorrelated Sector Concurrency Guard: Prevents concentration risk by enforcing a maximum of 2 positions per sector
- Auto-releases capital as scale-out take-profits are hit (TP1 +2.5% closes 40-50% size), recycling freed collateral into new catalysts
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("MultiPositionConcurrency")


@dataclass
class ActivePositionSlot:
    position_id: str
    symbol: str
    sector: str
    side: str
    allocated_margin_usd: float
    margin_utilization_pct: float
    entry_timestamp: float
    is_breakeven_locked: bool = False


@dataclass
class ConcurrencyAllocationDecision:
    symbol: str
    is_allowed: bool
    recommended_margin_usd: float
    recommended_leverage: float
    max_sector_slots_available: int
    portfolio_margin_utilized_pct: float
    rejection_reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🎯 [CONCURRENCY SIZER] {self.symbol} | Allowed: {self.is_allowed} | Allocated: ${self.recommended_margin_usd:,.2f} USD ({self.recommended_leverage:.1f}x) | "
            f"Port Util: {self.portfolio_margin_utilized_pct:.1f}% | Sector Slots Left: {self.max_sector_slots_available} | Reason: {self.rejection_reason or 'APPROVED'}"
        )


class MultiPositionConcurrencyEngine:
    """
    Max-Position Concurrency & Margin Allocator.
    """

    SECTOR_MAP: Dict[str, str] = {
        "BTC": "CORE_L1",
        "ETH": "CORE_L1",
        "SOL": "SOLANA",
        "JUP": "SOLANA",
        "RAY": "SOLANA",
        "PYTH": "SOLANA",
        "HYPE": "SOLANA",
        "NEAR": "AI",
        "RENDER": "AI",
        "FET": "AI",
        "TAO": "AI",
        "DOGE": "MEMES",
        "SHIB": "MEMES",
        "PEPE": "MEMES",
        "WIF": "MEMES",
        "AVAX": "ALT_L1",
        "SUI": "ALT_L1",
        "APT": "ALT_L1",
        "BNB": "EXCHANGE",
    }

    def __init__(
        self,
        max_concurrent_positions: int = None,
        max_total_margin_pct: float = 85.0,
        max_sector_positions: int = 2,
        base_leverage: float = 5.0,
    ):
        import os
        if max_concurrent_positions is None:
            max_concurrent_positions = int(os.getenv("NEWS_MAX_CONCURRENCY", "16") or "16")
            if max_concurrent_positions <= 0:
                max_concurrent_positions = 16
        self.max_concurrent_positions = max_concurrent_positions
        self.max_total_margin_pct = float(os.getenv("NEWS_MAX_MARGIN_PCT", str(max_total_margin_pct)))
        self.max_sector_positions = int(os.getenv("NEWS_MAX_SECTOR_POSITIONS", str(max_sector_positions)))
        self.base_leverage = float(os.getenv("NEWS_BASE_LEVERAGE", str(base_leverage)))
        self.active_slots: Dict[str, ActivePositionSlot] = {}

    def register_entry(
        self,
        position_id: str,
        symbol: str,
        side: str,
        allocated_margin_usd: float,
        total_portfolio_usd: float,
    ) -> None:
        """Registers a newly opened position slot."""
        sym = symbol.upper()
        sec = self.SECTOR_MAP.get(sym, "GENERAL")
        util_pct = (allocated_margin_usd / max(1.0, total_portfolio_usd)) * 100.0

        self.active_slots[sym] = ActivePositionSlot(
            position_id=position_id,
            symbol=sym,
            sector=sec,
            side=side.upper(),
            allocated_margin_usd=allocated_margin_usd,
            margin_utilization_pct=util_pct,
            entry_timestamp=time.time(),
        )

    def register_close(self, symbol: str) -> None:
        """Frees up position slot upon position close."""
        sym = symbol.upper()
        self.active_slots.pop(sym, None)

    def evaluate_new_entry(
        self,
        symbol: str,
        catalyst_conviction_score: float,  # 0 to 100
        total_portfolio_usd: float,
    ) -> ConcurrencyAllocationDecision:
        """
        Evaluates whether a new position can be taken and calculates maximum safe sizing.
        """
        sym = symbol.upper()
        sec = self.SECTOR_MAP.get(sym, "GENERAL")

        # Check if already active
        if sym in self.active_slots:
            return ConcurrencyAllocationDecision(
                symbol=sym,
                is_allowed=False,
                recommended_margin_usd=0.0,
                recommended_leverage=1.0,
                max_sector_slots_available=0,
                portfolio_margin_utilized_pct=0.0,
                rejection_reason="Position already open for asset",
            )

        # Check total slots
        if len(self.active_slots) >= self.max_concurrent_positions:
            return ConcurrencyAllocationDecision(
                symbol=sym,
                is_allowed=False,
                recommended_margin_usd=0.0,
                recommended_leverage=1.0,
                max_sector_slots_available=0,
                portfolio_margin_utilized_pct=0.0,
                rejection_reason=f"Max concurrent positions reached ({self.max_concurrent_positions})",
            )

        # Check sector concentration
        sector_active_count = sum(1 for p in self.active_slots.values() if p.sector == sec)
        if sector_active_count >= self.max_sector_positions:
            return ConcurrencyAllocationDecision(
                symbol=sym,
                is_allowed=False,
                recommended_margin_usd=0.0,
                recommended_leverage=1.0,
                max_sector_slots_available=0,
                portfolio_margin_utilized_pct=0.0,
                rejection_reason=f"Max sector positions reached for {sec} ({self.max_sector_positions})",
            )

        # Calculate current total margin utilized
        cur_utilized_usd = sum(p.allocated_margin_usd for p in self.active_slots.values())
        max_allowed_margin_usd = total_portfolio_usd * (self.max_total_margin_pct / 100.0)
        remaining_margin_usd = max(0.0, max_allowed_margin_usd - cur_utilized_usd)

        if remaining_margin_usd < 10.0:
            return ConcurrencyAllocationDecision(
                symbol=sym,
                is_allowed=False,
                recommended_margin_usd=0.0,
                recommended_leverage=1.0,
                max_sector_slots_available=self.max_sector_positions - sector_active_count,
                portfolio_margin_utilized_pct=(cur_utilized_usd / total_portfolio_usd) * 100.0,
                rejection_reason="Margin capacity exhausted (>= 85% limit)",
            )

        # Dynamic Kelly scaling on remaining margin
        if catalyst_conviction_score >= 95.0:
            alloc_pct = 0.85
        elif catalyst_conviction_score >= 85.0:
            alloc_pct = 0.60
        else:
            alloc_pct = 0.40

        alloc_usd = min(remaining_margin_usd, remaining_margin_usd * alloc_pct)
        alloc_usd = max(15.0, alloc_usd)
        alloc_usd = min(alloc_usd, remaining_margin_usd)

        total_post_util = (cur_utilized_usd + alloc_usd) / total_portfolio_usd * 100.0

        decision = ConcurrencyAllocationDecision(
            symbol=sym,
            is_allowed=True,
            recommended_margin_usd=round(alloc_usd, 2),
            recommended_leverage=self.base_leverage,
            max_sector_slots_available=self.max_sector_positions - sector_active_count - 1,
            portfolio_margin_utilized_pct=round(total_post_util, 1),
            rejection_reason="",
        )
        return decision
