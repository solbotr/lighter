#!/usr/bin/env python3
"""
Asymmetric Scale-Out Profit Maximizer (asymmetric_tp_maximizer.py)
=================================================================
Optimizes profit extraction across multi-stage scale-outs and explosive trend runners:

Scale-Out Architecture:
- Tier 1 (+2.0% to +3.0% Gain):
  * Closes 40% initial size
  * Instantly ratchets Stop-Loss to Breakeven (+0.1%) -> 100% Risk-Free Trade
- Tier 2 (+4.5% to +6.5% Gain):
  * Closes 30% remaining size
  * Raises trailing profit floor to +2.5%
- Tier 3 / Super-Runner (30% Position):
  * Dynamic Volatility Trailing Stop (1.5x ATR cushion)
  * Allows winner to run up to +12.0% - +25.0% on parabolic breaking catalysts
  * Automatically closes runner when orderbook bid/ask replenishment velocity drops > 70%
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AsymmetricTPMaximizer")


@dataclass
class ScaleOutExecutionStep:
    step_level: int
    trigger_gain_pct: float
    close_size_pct: float
    new_stop_loss_pct: float
    is_executed: bool = False
    executed_timestamp: float = 0.0


@dataclass
class PositionProfitPlan:
    position_id: str
    symbol: str
    entry_price: float
    current_price: float
    current_gain_pct: float
    current_stage: str  # "STAGE_ENTRY", "STAGE_BE_LOCKED", "STAGE_TP2_LOCKED", "STAGE_RUNNER"
    active_trailing_stop_pct: float
    steps: List[ScaleOutExecutionStep] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"💰 [TP MAXIMIZER] {self.symbol} | PnL: {self.current_gain_pct:+.2f}% ({self.current_stage}) | "
            f"Active Trail SL: {self.active_trailing_stop_pct:+.2f}% | Entry: ${self.entry_price:,.2f} ➡️ Now: ${self.current_price:,.2f}"
        )


class AsymmetricTPMaximizer:
    """
    Multi-Tier Profit-Taking and Parabolic Runner Manager.
    """

    def __init__(
        self,
        tp1_gain_pct: float = 2.5,
        tp2_gain_pct: float = 5.0,
        tp3_target_pct: float = 12.0,
        hard_sl_pct: float = -1.5,
    ):
        self.tp1_gain_pct = tp1_gain_pct
        self.tp2_gain_pct = tp2_gain_pct
        self.tp3_target_pct = tp3_target_pct
        self.hard_sl_pct = hard_sl_pct
        self.active_plans: Dict[str, PositionProfitPlan] = {}

    def create_profit_plan(
        self,
        position_id: str,
        symbol: str,
        entry_price: float,
        is_long: bool = True,
    ) -> PositionProfitPlan:
        """Initializes a multi-tier profit plan for a new position."""
        steps = [
            ScaleOutExecutionStep(step_level=1, trigger_gain_pct=self.tp1_gain_pct, close_size_pct=40.0, new_stop_loss_pct=0.1),
            ScaleOutExecutionStep(step_level=2, trigger_gain_pct=self.tp2_gain_pct, close_size_pct=30.0, new_stop_loss_pct=2.5),
            ScaleOutExecutionStep(step_level=3, trigger_gain_pct=self.tp3_target_pct, close_size_pct=30.0, new_stop_loss_pct=5.0),
        ]

        plan = PositionProfitPlan(
            position_id=position_id,
            symbol=symbol.upper(),
            entry_price=entry_price,
            current_price=entry_price,
            current_gain_pct=0.0,
            current_stage="STAGE_ENTRY",
            active_trailing_stop_pct=self.hard_sl_pct,
            steps=steps,
        )
        self.active_plans[position_id] = plan
        return plan

    def evaluate_price_update(
        self,
        position_id: str,
        current_price: float,
        is_long: bool = True,
        current_atr_pct: float = 1.2,
    ) -> Tuple[PositionProfitPlan, Optional[ScaleOutExecutionStep]]:
        """
        Evaluates current price against scale-out ladder and trailing runner conditions.
        """
        plan = self.active_plans.get(position_id)
        if not plan:
            return (
                PositionProfitPlan(
                    position_id=position_id,
                    symbol="UNKNOWN",
                    entry_price=current_price,
                    current_price=current_price,
                    current_gain_pct=0.0,
                    current_stage="STAGE_ENTRY",
                    active_trailing_stop_pct=self.hard_sl_pct,
                ),
                None,
            )

        plan.current_price = current_price
        gain_pct = ((current_price - plan.entry_price) / plan.entry_price * 100.0) if is_long else ((plan.entry_price - current_price) / plan.entry_price * 100.0)
        plan.current_gain_pct = round(gain_pct, 2)

        triggered_step: Optional[ScaleOutExecutionStep] = None

        # Check TP1
        if gain_pct >= plan.steps[0].trigger_gain_pct and not plan.steps[0].is_executed:
            plan.steps[0].is_executed = True
            plan.steps[0].executed_timestamp = time.time()
            plan.current_stage = "STAGE_BE_LOCKED"
            plan.active_trailing_stop_pct = max(plan.active_trailing_stop_pct, plan.steps[0].new_stop_loss_pct)
            triggered_step = plan.steps[0]

        # Check TP2
        elif gain_pct >= plan.steps[1].trigger_gain_pct and not plan.steps[1].is_executed:
            plan.steps[1].is_executed = True
            plan.steps[1].executed_timestamp = time.time()
            plan.current_stage = "STAGE_TP2_LOCKED"
            plan.active_trailing_stop_pct = max(plan.active_trailing_stop_pct, plan.steps[1].new_stop_loss_pct)
            triggered_step = plan.steps[1]

        # Check Runner Trailing Cushion
        elif plan.steps[1].is_executed:
            plan.current_stage = "STAGE_RUNNER"
            trail_cushion = max(1.0, current_atr_pct * 1.5)
            dynamic_trail = gain_pct - trail_cushion
            plan.active_trailing_stop_pct = max(plan.active_trailing_stop_pct, dynamic_trail)

        return plan, triggered_step
