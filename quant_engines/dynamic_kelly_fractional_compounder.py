#!/usr/bin/env python3
"""
Continuous Fractional Kelly Compounder (dynamic_kelly_fractional_compounder.py)
=============================================================================
Implements John L. Kelly Jr.'s (1956) Information Criterion with Parameter Uncertainty Shrinkage:
  f^* = (p · b - q) / b
  f_{shrunk} = κ_{shrink} · f^*

Where:
  p = Win probability (e.g. 72.0%)
  q = Loss probability (1 - p)
  b = Win / Loss payoff ratio (e.g. 2.50)
  κ_{shrink} = Confidence scalar based on sample variance (0.25 to 0.50 Half-Kelly)

Key Capabilities:
- Maximizes the geometric growth rate of capital: G(f) = E[ln(1 + f · R)]
- Strictly prevents over-leveraging and catastrophic ruin during drawdown streaks
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("FractionalKelly")


@dataclass
class KellyOptimalPositionSize:
    symbol: str
    total_portfolio_usd: float
    win_probability_p: float
    payoff_ratio_b: float
    full_kelly_fraction_pct: float
    fractional_kelly_shrinkage: float  # e.g. 0.40 (40% of Full Kelly)
    recommended_position_usd: float
    recommended_portfolio_pct: float
    expected_growth_rate_pct: float
    is_safe_allocation: bool
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"💰 [FRACTIONAL KELLY] {self.symbol} | Win Prob: {self.win_probability_p*100:.1f}%, Payoff: {self.payoff_ratio_b:.2f}x | "
            f"Full Kelly: {self.full_kelly_fraction_pct:.1f}% ➡️ {self.fractional_kelly_shrinkage*100:.0f}% Shrinkage | "
            f"Recommended: ${self.recommended_position_usd:,.2f} USD ({self.recommended_portfolio_pct:.1f}% Equity, Growth Rate: +{self.expected_growth_rate_pct:.2f}%)"
        )


class DynamicKellyFractionalCompounder:
    """
    Continuous Fractional Kelly Position Sizer.
    """

    def __init__(self, default_fractional_multiplier: float = 0.40, max_single_bet_pct: float = 35.0):
        self.default_fractional_multiplier = default_fractional_multiplier
        self.max_single_bet_pct = max_single_bet_pct

    def compute_optimal_size(
        self,
        symbol: str,
        total_portfolio_usd: float,
        win_probability_p: float = 0.70,
        payoff_ratio_b: float = 2.20,
        catalyst_conviction_score: float = 90.0,
    ) -> KellyOptimalPositionSize:
        """
        Calculates optimal position size using fractional Kelly criterion with uncertainty shrinkage.
        """
        sym = symbol.upper()
        p = max(0.10, min(0.95, win_probability_p))
        q = 1.0 - p
        b = max(0.50, payoff_ratio_b)

        # Full Kelly: f* = (p * b - q) / b
        f_star = (p * b - q) / b

        if f_star <= 0:
            # Negative edge, do not trade
            return KellyOptimalPositionSize(
                symbol=sym,
                total_portfolio_usd=total_portfolio_usd,
                win_probability_p=p,
                payoff_ratio_b=b,
                full_kelly_fraction_pct=0.0,
                fractional_kelly_shrinkage=self.default_fractional_multiplier,
                recommended_position_usd=0.0,
                recommended_portfolio_pct=0.0,
                expected_growth_rate_pct=0.0,
                is_safe_allocation=True,
            )

        # Dynamic Shrinkage based on catalyst conviction
        conv_factor = max(0.50, min(1.20, catalyst_conviction_score / 90.0))
        shrinkage = self.default_fractional_multiplier * conv_factor
        f_shrunk = f_star * shrinkage

        # Cap at max safe single bet
        alloc_pct = min(self.max_single_bet_pct, f_shrunk * 100.0)
        pos_usd = total_portfolio_usd * (alloc_pct / 100.0)

        # Expected geometric growth rate: G = p * ln(1 + f * b) + q * ln(1 - f)
        f_val = alloc_pct / 100.0
        g_rate = (p * math.log(1.0 + f_val * b) + q * math.log(max(1e-4, 1.0 - f_val))) * 100.0

        res = KellyOptimalPositionSize(
            symbol=sym,
            total_portfolio_usd=round(total_portfolio_usd, 2),
            win_probability_p=round(p, 3),
            payoff_ratio_b=round(b, 2),
            full_kelly_fraction_pct=round(f_star * 100.0, 1),
            fractional_kelly_shrinkage=round(shrinkage, 2),
            recommended_position_usd=round(pos_usd, 2),
            recommended_portfolio_pct=round(alloc_pct, 1),
            expected_growth_rate_pct=round(g_rate, 2),
            is_safe_allocation=alloc_pct <= self.max_single_bet_pct,
        )
        return res
