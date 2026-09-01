#!/usr/bin/env python3
"""
Auto-Trailing Parabolic Profit Step-Lock Engine (parabolic_profit_steplock.py)
=============================================================================
Institutional-grade profit lock-in mechanism for explosive multi-day runners:
- Calculates dynamic step-up profit floors based on highest favorable excursion (MFE).
- Progressively shifts Stop-Loss into positive profit territory:
  * Gain >= +3.0% -> Lock in Breakeven (+0.1%)
  * Gain >= +5.0% -> Lock in +3.0% Guaranteed Profit
  * Gain >= +10.0% -> Lock in +7.5% Guaranteed Profit
  * Gain >= +20.0% -> Lock in +16.0% Guaranteed Profit
- Protects open gains against sharp wick retracements while keeping runners active.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Tuple

logger = logging.getLogger("ParabolicProfitStepLock")

# Thresholds: (min_gain_pct, locked_profit_pct)
STEP_LOCK_LADDER = [
    (20.0, 16.0),
    (10.0, 7.5),
    (5.0, 3.0),
    (3.0, 0.1),  # Breakeven floor
]


@dataclass(frozen=True)
class StepLockResult:
    is_updated: bool
    current_gain_pct: float
    locked_profit_pct: float
    new_sl_price: float
    reason: str


def calculate_parabolic_steplock(
    side: str,
    entry_price: float,
    current_mark_price: float,
    highest_price: float = 0.0,
    lowest_price: float = float("inf"),
    existing_sl_price: float = 0.0,
) -> StepLockResult:
    if entry_price <= 0 or current_mark_price <= 0:
        return StepLockResult(False, 0.0, 0.0, existing_sl_price, "Invalid price")

    is_long = side.upper().startswith("BUY") or side.upper() == "LONG"
    
    # Calculate Maximum Favorable Excursion (MFE) %
    if is_long:
        peak = max(current_mark_price, highest_price or entry_price)
        gain_pct = ((peak - entry_price) / entry_price) * 100.0
    else:
        trough = min(current_mark_price, lowest_price if lowest_price != float("inf") else entry_price)
        gain_pct = ((entry_price - trough) / entry_price) * 100.0

    # Determine highest applicable profit tier
    applied_lock_pct = 0.0
    for threshold_pct, lock_pct in STEP_LOCK_LADDER:
        if gain_pct >= threshold_pct:
            applied_lock_pct = lock_pct
            break

    if applied_lock_pct <= 0.0:
        return StepLockResult(False, gain_pct, 0.0, existing_sl_price, "Below minimum step-lock threshold")

    # Compute candidate SL price
    if is_long:
        candidate_sl = round(entry_price * (1.0 + (applied_lock_pct / 100.0)), 6)
        if existing_sl_price <= 0 or candidate_sl > existing_sl_price:
            return StepLockResult(
                is_updated=True,
                current_gain_pct=gain_pct,
                locked_profit_pct=applied_lock_pct,
                new_sl_price=candidate_sl,
                reason=f"MFE +{gain_pct:.2f}% triggered +{applied_lock_pct:.2f}% profit lock floor",
            )
    else:
        candidate_sl = round(entry_price * (1.0 - (applied_lock_pct / 100.0)), 6)
        if existing_sl_price <= 0 or candidate_sl < existing_sl_price:
            return StepLockResult(
                is_updated=True,
                current_gain_pct=gain_pct,
                locked_profit_pct=applied_lock_pct,
                new_sl_price=candidate_sl,
                reason=f"MFE +{gain_pct:.2f}% triggered +{applied_lock_pct:.2f}% profit lock floor",
            )

    return StepLockResult(False, gain_pct, applied_lock_pct, existing_sl_price, "Existing SL already higher")
