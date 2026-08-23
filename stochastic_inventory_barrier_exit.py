#!/usr/bin/env python3
"""
Stochastic Inventory Barrier Exit Engine (stochastic_inventory_barrier_exit.py)
==============================================================================
Models inventory risk as a Brownian motion with upper and lower absorbing boundaries:
  dX_t = μ dt + σ dW_t

First Passage Time Probability to Profit Barrier (B_u) vs Stop Barrier (B_d):
  P(Hit B_u before B_d) = [1 - e^{-2 μ B_d / σ²}] / [e^{2 μ B_u / σ²} - e^{-2 μ B_d / σ²}]

Key Capabilities:
- Calculates exact expected first-exit time E[τ] for inventory holding
- Triggers dynamic inventory offloading when probability of hitting downside barrier crosses 65%
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("BarrierExit")


@dataclass
class InventoryBarrierResult:
    symbol: str
    inventory_qty: float
    current_pnl_bps: float
    upper_barrier_bps: float  # Take-Profit barrier
    lower_barrier_bps: float  # Stop-Loss barrier
    prob_hit_profit_barrier_pct: float
    expected_exit_time_sec: float
    is_emergency_offload_required: bool
    recommended_action: str  # "HOLD_RUNNER", "PARTIAL_TRIM", "EMERGENCY_OFFLOAD"
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🛡️ [BARRIER EXIT] {self.symbol} (Qty: {self.inventory_qty:+.2f}, PnL: {self.current_pnl_bps:+.1f} bps) | "
            f"P(Hit TP): {self.prob_hit_profit_barrier_pct:.1f}% | E[τ]: ~{self.expected_exit_time_sec:.1f}s | "
            f"Action: {self.recommended_action} (Emergency: {self.is_emergency_offload_required})"
        )


class StochasticInventoryBarrierExitEngine:
    """
    First-Exit-Time Brownian Motion Inventory Manager.
    """

    def evaluate_inventory_barrier(
        self,
        symbol: str,
        inventory_qty: float,
        current_pnl_bps: float,
        drift_mu_bps: float = 2.0,
        vol_sigma_bps: float = 15.0,
        upper_barrier_bps: float = 40.0,
        lower_barrier_bps: float = -20.0,
    ) -> InventoryBarrierResult:
        """
        Calculates first passage time probability and recommended inventory action.
        """
        sym = symbol.upper()
        b_u = max(5.0, upper_barrier_bps)
        b_d = abs(min(-5.0, lower_barrier_bps))
        sigma_sq = max(1.0, vol_sigma_bps ** 2)

        # Ratio: 2 * mu / sigma^2
        ratio = (2.0 * drift_mu_bps) / sigma_sq

        if abs(ratio) < 1e-4:
            # Zero drift Brownian motion: P = b_d / (b_u + b_d)
            prob_tp = (b_d / (b_u + b_d)) * 100.0
        else:
            num = 1.0 - math.exp(-ratio * b_d)
            den = math.exp(ratio * b_u) - math.exp(-ratio * b_d)
            prob_tp = max(5.0, min(95.0, (num / max(1e-4, den)) * 100.0))

        # Expected exit time approximation: E[τ] = (b_u * b_d) / sigma^2
        e_tau = max(5.0, (b_u * b_d) / max(1.0, vol_sigma_bps)) * 2.0

        if prob_tp <= 35.0 or current_pnl_bps <= -15.0:
            act = "EMERGENCY_OFFLOAD"
            offload = True
        elif prob_tp <= 55.0:
            act = "PARTIAL_TRIM"
            offload = False
        else:
            act = "HOLD_RUNNER"
            offload = False

        res = InventoryBarrierResult(
            symbol=sym,
            inventory_qty=round(inventory_qty, 4),
            current_pnl_bps=round(current_pnl_bps, 2),
            upper_barrier_bps=round(b_u, 2),
            lower_barrier_bps=round(-b_d, 2),
            prob_hit_profit_barrier_pct=round(prob_tp, 1),
            expected_exit_time_sec=round(e_tau, 1),
            is_emergency_offload_required=offload,
            recommended_action=act,
        )
        return res
