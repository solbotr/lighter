#!/usr/bin/env python3
"""
Almgren-Chriss Optimal Execution Trajectory Engine (almgren_chriss_execution.py)
==============================================================================
Implements the foundational Robert Almgren & Neil Chriss (2000) optimal execution model:
  x_j = (sinh(κ(T - t_j)) / sinh(κT)) · X_0

Where:
  κ ≈ sqrt(λ_risk · σ² / η_temp)
  λ_risk = Trader risk aversion
  σ = Asset volatility
  η_temp = Temporary market impact coefficient

Key Capabilities:
- Calculates mathematically optimal schedule of discrete child slice sizes
- Balances market impact against timing risk to minimize Total Expected Execution Cost
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AlmgrenChriss")


@dataclass
class ExecutionTrajectoryStep:
    step_index: int
    scheduled_time_sec: float
    remaining_inventory_usd: float
    trade_chunk_usd: float
    optimal_intensity_pct: float


@dataclass
class AlmgrenChrissSchedule:
    schedule_id: str
    symbol: str
    side: str
    total_notional_usd: float
    total_duration_seconds: float
    num_steps: int
    kappa_urgency: float
    expected_shortfall_cost_bps: float
    variance_of_shortfall_bps: float
    steps: List[ExecutionTrajectoryStep] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"⚡ [ALMGREN-CHRISS] {self.side} ${self.total_notional_usd:,.2f} {self.symbol} | "
            f"Duration: {self.total_duration_seconds:.1f}s across {self.num_steps} slices (κ={self.kappa_urgency:.3f}) | "
            f"Expected Shortfall Cost: {self.expected_shortfall_cost_bps:.2f} bps (Var: {self.variance_of_shortfall_bps:.2f})"
        )


class AlmgrenChrissExecutionEngine:
    """
    Optimal Execution Schedule Calculator.
    """

    def __init__(
        self,
        risk_aversion_lambda: float = 1e-4,
        temporary_impact_eta: float = 2.5e-5,
        permanent_impact_gamma: float = 1.0e-6,
    ):
        self.risk_aversion_lambda = risk_aversion_lambda
        self.temporary_impact_eta = temporary_impact_eta
        self.permanent_impact_gamma = permanent_impact_gamma

    def calculate_optimal_schedule(
        self,
        symbol: str,
        side: str,
        total_usd: float,
        volatility_sigma: float = 0.02,  # Hourly std dev
        total_duration_seconds: float = 10.0,
        num_steps: int = 5,
    ) -> AlmgrenChrissSchedule:
        """
        Computes the Almgren-Chriss optimal liquidation trajectory.
        """
        sym = symbol.upper()
        T = total_duration_seconds
        N = max(2, num_steps)
        tau = T / N

        # Kappa urgency parameter: κ ≈ sqrt(λ * σ² / η)
        var = max(1e-6, volatility_sigma ** 2)
        kappa = math.sqrt((self.risk_aversion_lambda * var) / self.temporary_impact_eta)
        kappa = max(0.01, min(5.0, kappa))

        steps: List[ExecutionTrajectoryStep] = []
        x_prev = total_usd
        sinh_kT = math.sinh(min(50.0, kappa * T))

        for j in range(1, N + 1):
            t_j = j * tau
            # Remaining inventory: x_j = X_0 * sinh(κ(T - t_j)) / sinh(κT)
            if j == N:
                x_j = 0.0
            else:
                sinh_rem = math.sinh(min(50.0, kappa * (T - t_j)))
                x_j = total_usd * (sinh_rem / sinh_kT) if sinh_kT > 0 else 0.0

            chunk = max(0.0, x_prev - x_j)
            steps.append(
                ExecutionTrajectoryStep(
                    step_index=j,
                    scheduled_time_sec=round(t_j, 2),
                    remaining_inventory_usd=round(x_j, 2),
                    trade_chunk_usd=round(chunk, 2),
                    optimal_intensity_pct=round((chunk / total_usd) * 100.0, 1) if total_usd > 0 else 0.0,
                )
            )
            x_prev = x_j

        # Expected Shortfall in bps: E[x] ≈ 0.5 * γ * X_0 + η * ∑ (chunk² / tau)
        perm_cost = 0.5 * self.permanent_impact_gamma * total_usd
        temp_cost = self.temporary_impact_eta * sum((s.trade_chunk_usd ** 2) / tau for s in steps)
        est_cost_bps = ((perm_cost + temp_cost) / total_usd) * 10000.0 if total_usd > 0 else 0.0
        var_cost_bps = (self.risk_aversion_lambda * var * (total_usd ** 2)) / 1000.0

        schedule = AlmgrenChrissSchedule(
            schedule_id=f"ac_{sym}_{int(time.time()*1000)}",
            symbol=sym,
            side=side.upper(),
            total_notional_usd=total_usd,
            total_duration_seconds=T,
            num_steps=N,
            kappa_urgency=round(kappa, 4),
            expected_shortfall_cost_bps=round(max(0.5, est_cost_bps), 2),
            variance_of_shortfall_bps=round(var_cost_bps, 2),
            steps=steps,
        )
        return schedule
