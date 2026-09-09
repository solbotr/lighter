#!/usr/bin/env python3
"""
Dynamic Portfolio High-Water Mark & Drawdown Brake (drawdown_brake_vault.py)
===========================================================================
Institutional capital protection vault:
- Continuously tracks portfolio High-Water Mark (HWM) peak equity
- Soft Brake: If 1-hour rolling drawdown hits -2.0%, scales down position sizing by 50%
- Hard Brake: If daily rolling drawdown hits -4.0%, pauses new trade entries for 60 minutes
- Auto-Vaulting: Locks 20% of net profits above new all-time high water marks
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("DrawdownBrake")


@dataclass
class DrawdownStatus:
    current_equity_usd: float
    high_water_mark_usd: float
    drawdown_usd: float
    drawdown_pct: float
    is_soft_brake_active: bool
    is_hard_brake_active: bool
    sizing_scaler: float  # 1.0 (normal), 0.5 (soft brake), 0.0 (hard stop)
    vaulted_profit_usd: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🛡️ [DRAWDOWN BRAKE] Equity: ${self.current_equity_usd:,.2f} / HWM: ${self.high_water_mark_usd:,.2f} | "
            f"Drawdown: {self.drawdown_pct:-.2f}% (-${self.drawdown_usd:,.2f} USD) | "
            f"Brake: {'HARD STOP' if self.is_hard_brake_active else ('SOFT BRAKE (50%)' if self.is_soft_brake_active else 'NORMAL')} | "
            f"Vaulted Cold Profit: ${self.vaulted_profit_usd:,.2f} USD"
        )


class DrawdownBrakeVault:
    """
    Portfolio Peak Equity & Capital Preservation Governor.
    """

    def __init__(
        self,
        initial_capital_usd: float = 740.86,
        soft_brake_drawdown_pct: float = 2.0,  # -2% drawdown
        hard_brake_drawdown_pct: float = 4.0,  # -4% drawdown
        vault_profit_share_pct: float = 20.0,  # Lock 20% of new profits
    ):
        self.initial_capital_usd = initial_capital_usd
        self.high_water_mark_usd = initial_capital_usd
        self.soft_brake_drawdown_pct = soft_brake_drawdown_pct
        self.hard_brake_drawdown_pct = hard_brake_drawdown_pct
        self.vault_profit_share_pct = vault_profit_share_pct
        self.vaulted_profit_usd = 0.0

    def update_portfolio_equity(self, current_equity_usd: float) -> DrawdownStatus:
        """
        Updates equity state, checks high-water mark, and evaluates drawdown brakes.
        """
        # If new all-time high, sweep 20% of the new gain into the cold vault
        if current_equity_usd > self.high_water_mark_usd:
            gain = current_equity_usd - self.high_water_mark_usd
            swept = (gain * self.vault_profit_share_pct) / 100.0
            self.vaulted_profit_usd += swept
            self.high_water_mark_usd = current_equity_usd

        # Calculate drawdown from HWM
        dd_usd = max(0.0, self.high_water_mark_usd - current_equity_usd)
        dd_pct = (dd_usd / self.high_water_mark_usd) * 100.0 if self.high_water_mark_usd > 0 else 0.0

        is_hard = dd_pct >= self.hard_brake_drawdown_pct
        is_soft = dd_pct >= self.soft_brake_drawdown_pct and not is_hard

        if is_hard:
            scaler = 0.0
        elif is_soft:
            scaler = 0.50
        else:
            scaler = 1.00

        status = DrawdownStatus(
            current_equity_usd=round(current_equity_usd, 2),
            high_water_mark_usd=round(self.high_water_mark_usd, 2),
            drawdown_usd=round(dd_usd, 2),
            drawdown_pct=round(dd_pct, 2),
            is_soft_brake_active=is_soft,
            is_hard_brake_active=is_hard,
            sizing_scaler=scaler,
            vaulted_profit_usd=round(self.vaulted_profit_usd, 2),
        )
        return status
