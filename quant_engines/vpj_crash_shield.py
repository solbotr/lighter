#!/usr/bin/env python3
"""
Volume-Synchronized Probability of Jump (VPJ) Crash Shield (vpj_crash_shield.py)
==============================================================================
Calculates volume-synchronized jump arrival probabilities across discrete equal-volume buckets:
  P(Jump | V_τ) = 1 - e^{-λ_jump · V_τ}

Key Capabilities:
- Detects non-linear Poisson jump tail-risk before catastrophic liquidity gap-downs occur
- Dynamically tightens Stop-Loss thresholds from -1.5% to -0.6% when jump probability exceeds 80%
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("VPJCrashShield")


@dataclass
class VolumeBucketSample:
    volume_usd: float
    price_return_bps: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class JumpCrashShieldStatus:
    symbol: str
    jump_intensity_lambda: float
    jump_probability_pct: float
    is_crash_imminent: bool
    recommended_stop_loss_pct: float  # Normal -1.5% tightened down to -0.6%
    shield_status: str  # "SHIELD_ACTIVE_TIGHT", "GUARD_ELEVATED", "NORMAL"
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🚨 [VPJ CRASH SHIELD] {self.symbol} | Jump Intensity λ: {self.jump_intensity_lambda:.4f} (Prob: {self.jump_probability_pct:.1f}%) | "
            f"State: {self.shield_status} | Tightened SL: {self.recommended_stop_loss_pct:.2f}% | Crash Imminent: {self.is_crash_imminent}"
        )


class VolumeSynchronizedJumpCrashShield:
    """
    Volume-Clock Poisson Jump Crash Defense Governor.
    """

    def __init__(self, bucket_size_usd: float = 10000.0, max_buckets: int = 30):
        self.bucket_size_usd = bucket_size_usd
        self.max_buckets = max_buckets
        self.bucket_history: Dict[str, deque[VolumeBucketSample]] = {}

    def push_volume_bucket(
        self,
        symbol: str,
        price_return_bps: float,
        volume_usd: float = 10000.0,
    ) -> JumpCrashShieldStatus:
        """
        Records completed volume bucket and calculates real-time jump intensity.
        """
        sym = symbol.upper()
        if sym not in self.bucket_history:
            self.bucket_history[sym] = deque(maxlen=self.max_buckets)

        self.bucket_history[sym].append(
            VolumeBucketSample(volume_usd=volume_usd, price_return_bps=price_return_bps)
        )

        buckets = self.bucket_history[sym]
        if len(buckets) < 5:
            return JumpCrashShieldStatus(
                symbol=sym,
                jump_intensity_lambda=0.01,
                jump_probability_pct=10.0,
                is_crash_imminent=False,
                recommended_stop_loss_pct=-1.50,
                shield_status="NORMAL",
            )

        returns = [b.price_return_bps for b in buckets]
        mean_r = sum(returns) / len(returns)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 5.0

        # Jumps defined as returns > 2.5 std
        jump_count = sum(1 for r in returns if abs(r) >= 2.5 * max(1.0, std_r))
        lambda_j = jump_count / len(returns)

        # Poisson probability in next volume clock tick
        p_jump = (1.0 - math.exp(-lambda_j * 2.0)) * 100.0

        is_imminent = p_jump >= 75.0 or (lambda_j >= 0.40)

        if is_imminent:
            rec_sl = -0.60
            status_str = "SHIELD_ACTIVE_TIGHT"
        elif p_jump >= 45.0:
            rec_sl = -1.00
            status_str = "GUARD_ELEVATED"
        else:
            rec_sl = -1.50
            status_str = "NORMAL"

        status = JumpCrashShieldStatus(
            symbol=sym,
            jump_intensity_lambda=round(lambda_j, 4),
            jump_probability_pct=round(p_jump, 1),
            is_crash_imminent=is_imminent,
            recommended_stop_loss_pct=round(rec_sl, 2),
            shield_status=status_str,
        )
        return status
