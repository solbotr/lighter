#!/usr/bin/env python3
"""
PnL-Preserving Daily Trailing Ratchet Vault (trailing_ratchet_vault.py)
=====================================================================
One-way upward profit locking ratchet:
- Milestone Floor Locks:
  - At +2.0% daily gain: Locks in +1.0% floor (cannot drop below +1.0%)
  - At +4.0% daily gain: Locks in +3.0% floor (cannot drop below +3.0%)
  - At +6.0% daily gain: Locks in +5.0% floor (cannot drop below +5.0%)
- Instant Daily Profit Lock: If equity drops to the locked floor, immediately cancels maker quotes
  and freezes trading until the next 00:00 UTC daily session reset.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("TrailingRatchetVault")


@dataclass
class RatchetState:
    session_start_equity_usd: float
    current_equity_usd: float
    daily_pnl_usd: float
    daily_pnl_pct: float
    peak_daily_pnl_pct: float
    locked_floor_pnl_pct: float
    locked_floor_equity_usd: float
    is_ratchet_floor_breached: bool
    is_trading_locked_for_session: bool
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🛡️ [RATCHET VAULT] Current: ${self.current_equity_usd:,.2f} ({self.daily_pnl_pct:+.2f}%) | "
            f"Peak Gain: +{self.peak_daily_pnl_pct:.2f}% ➡️ Locked Floor: +{self.locked_floor_pnl_pct:.2f}% (${self.locked_floor_equity_usd:,.2f} USD) | "
            f"Session Locked: {self.is_trading_locked_for_session}"
        )


class TrailingRatchetVault:
    """
    Daily Profit Ratchet & Lockout Controller.
    """

    # Milestone locks: (peak_gain_pct_trigger, locked_floor_gain_pct)
    RATCHET_TIERS = [
        (6.0, 5.0),
        (4.0, 3.0),
        (2.0, 1.0),
    ]

    def __init__(self, session_start_equity_usd: float = 740.86):
        self.session_start_equity_usd = session_start_equity_usd
        self.peak_daily_pnl_pct = 0.0
        self.locked_floor_pnl_pct = 0.0
        self.is_locked = False

    def update_session_equity(self, current_equity_usd: float) -> RatchetState:
        """
        Updates session equity, advances ratchet floor upward, and checks breach conditions.
        """
        pnl_usd = current_equity_usd - self.session_start_equity_usd
        pnl_pct = (pnl_usd / self.session_start_equity_usd) * 100.0 if self.session_start_equity_usd > 0 else 0.0

        if pnl_pct > self.peak_daily_pnl_pct:
            self.peak_daily_pnl_pct = pnl_pct

        # Advance ratchet floor if new tier achieved
        for trigger_pct, floor_pct in self.RATCHET_TIERS:
            if self.peak_daily_pnl_pct >= trigger_pct and floor_pct > self.locked_floor_pnl_pct:
                self.locked_floor_pnl_pct = floor_pct
                logger.info(f"🔒 [RATCHET LOCKED] New Profit Floor Locked at +{floor_pct:.1f}% (${self.session_start_equity_usd * (1.0 + floor_pct/100.0):,.2f} USD)!")
                break

        floor_usd = self.session_start_equity_usd * (1.0 + (self.locked_floor_pnl_pct / 100.0))
        breached = (self.locked_floor_pnl_pct > 0.0) and (current_equity_usd <= floor_usd)

        if breached and not self.is_locked:
            self.is_locked = True
            logger.critical("🚨 [RATCHET BREACH] Daily profit floor reached! Freezing session to preserve profits.")

        state = RatchetState(
            session_start_equity_usd=round(self.session_start_equity_usd, 2),
            current_equity_usd=round(current_equity_usd, 2),
            daily_pnl_usd=round(pnl_usd, 2),
            daily_pnl_pct=round(pnl_pct, 2),
            peak_daily_pnl_pct=round(self.peak_daily_pnl_pct, 2),
            locked_floor_pnl_pct=round(self.locked_floor_pnl_pct, 2),
            locked_floor_equity_usd=round(floor_usd, 2),
            is_ratchet_floor_breached=breached,
            is_trading_locked_for_session=self.is_locked,
        )
        return state
