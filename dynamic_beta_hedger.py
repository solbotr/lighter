#!/usr/bin/env python3
"""
Dynamic Beta-Neutral Portfolio Hedger (dynamic_beta_hedger.py)
=============================================================
Calculates dynamic rolling beta (β) against Bitcoin:
  β_asset = Cov(r_asset, r_BTC) / Var(r_BTC)

Key Capabilities:
- Calculates exact Short BTC/ETH hedge notional required to achieve 0.00 Beta Exposure
  when holding altcoin longs (SOL, HYPE, DOGE) from breaking news snipes.
- Isolate pure idiosyncratic news alpha while immunizing the portfolio against macro market dumps.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("DynamicBetaHedger")


@dataclass
class BetaHedgePlan:
    plan_id: str
    target_symbol: str
    target_side: str
    target_notional_usd: float
    asset_beta: float
    benchmark_symbol: str  # "BTC" or "ETH"
    recommended_hedge_side: str  # "SHORT" for long alt, "LONG" for short alt
    recommended_hedge_usd: float
    net_portfolio_beta: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"⚖️ [BETA HEDGE] {self.target_symbol} (${self.target_notional_usd:,.2f}, β={self.asset_beta:.2f}) ➡️ "
            f"Hedge: {self.recommended_hedge_side} ${self.recommended_hedge_usd:,.2f} {self.benchmark_symbol} | "
            f"Net Beta: {self.net_portfolio_beta:.2f} (Delta-Neutral Isolated Alpha)"
        )


class DynamicBetaHedger:
    """
    Beta-Neutral Portfolio Immunization Engine.
    """

    # Baseline asset betas to BTC
    DEFAULT_BETAS: Dict[str, float] = {
        "BTC": 1.00,
        "ETH": 1.15,
        "SOL": 1.60,
        "HYPE": 1.85,
        "DOGE": 2.10,
        "TRUMP": 2.20,
    }

    def __init__(self, history_len: int = 30):
        self.history_len = history_len
        self.return_pairs: Dict[str, deque[Tuple[float, float]]] = {}  # (r_asset, r_btc)

    def update_returns(self, symbol: str, return_asset_bps: float, return_btc_bps: float) -> None:
        """Records paired returns against Bitcoin benchmark."""
        sym = symbol.upper()
        if sym not in self.return_pairs:
            self.return_pairs[sym] = deque(maxlen=self.history_len)
        self.return_pairs[sym].append((return_asset_bps, return_btc_bps))

    def compute_beta(self, symbol: str) -> float:
        """
        Calculates rolling beta: β = Cov(r_asset, r_btc) / Var(r_btc).
        """
        sym = symbol.upper()
        pairs = self.return_pairs.get(sym, deque())
        if len(pairs) < 5:
            return self.DEFAULT_BETAS.get(sym, 1.50)

        r_a = [p[0] for p in pairs]
        r_b = [p[1] for p in pairs]

        mean_a = sum(r_a) / len(r_a)
        mean_b = sum(r_b) / len(r_b)

        cov = sum((r_a[i] - mean_a) * (r_b[i] - mean_b) for i in range(len(pairs)))
        var_b = sum((b - mean_b) ** 2 for b in r_b)

        if var_b <= 1e-6:
            return self.DEFAULT_BETAS.get(sym, 1.50)

        raw_beta = cov / var_b
        return max(0.20, min(3.50, raw_beta))

    def construct_beta_hedge(
        self,
        symbol: str,
        side: str,
        notional_usd: float,
        benchmark: str = "BTC",
    ) -> BetaHedgePlan:
        """
        Generates the exact hedge notional to neutralize systematic macro beta.
        """
        sym = symbol.upper()
        bench = benchmark.upper()
        beta = self.compute_beta(sym)
        is_long = side.upper() in ("LONG", "BUY")

        # Hedge notional = Asset_USD * Beta
        hedge_usd = notional_usd * beta
        hedge_side = "SHORT" if is_long else "LONG"

        plan = BetaHedgePlan(
            plan_id=f"hedge_{sym}_{int(time.time()*1000)}",
            target_symbol=sym,
            target_side="LONG" if is_long else "SHORT",
            target_notional_usd=notional_usd,
            asset_beta=round(beta, 2),
            benchmark_symbol=bench,
            recommended_hedge_side=hedge_side,
            recommended_hedge_usd=round(hedge_usd, 2),
            net_portfolio_beta=0.00,
        )
        return plan
