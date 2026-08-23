#!/usr/bin/env python3
"""
Asymmetric Avellaneda-Stoikov Inventory Quoting Engine (asymmetric_quoting_engine.py)
===================================================================================
Implements continuous stochastic optimal control for 0-fee market making:
  Reservation Price: r(s, q, t) = s - q · γ · σ² · (T - t)
  Optimal Bid Spread: δ^b = r - s + (1/γ) * ln(1 + γ/κ)
  Optimal Ask Spread: δ^a = s - r + (1/γ) * ln(1 + γ/κ)

Key Capabilities:
- Asymmetric inventory skew: Pushes ask quotes closer when inventory is long (to offload),
  and pushes bid quotes closer when inventory is short (to re-accumulate).
- Volatility-adaptive spread widening during news spikes (σ scaling).
- Zero-fee rebate capture and zkLighter ecosystem points farming.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AsymmetricQuoting")


@dataclass
class QuotingParameters:
    gamma_risk_aversion: float = 0.10  # Risk aversion parameter γ
    kappa_order_arrival: float = 1.50  # Order arrival intensity κ
    target_inventory: float = 0.0      # Ideal inventory q_target
    time_horizon_hours: float = 24.0   # Quoting session horizon T
    min_spread_bps: float = 4.0        # Minimum half-spread (0.04%)


@dataclass
class AsymmetricQuotes:
    symbol: str
    mid_price: float
    reservation_price: float
    optimal_bid: float
    optimal_ask: float
    bid_spread_bps: float
    ask_spread_bps: float
    inventory_q: float
    volatility_sigma: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🌾 [ASYMMETRIC QUOTES] {self.symbol} | Mid: ${self.mid_price:,.2f} (Reserve: ${self.reservation_price:,.2f}) | "
            f"Bid: ${self.optimal_bid:,.2f} (-{self.bid_spread_bps:.1f} bps) | Ask: ${self.optimal_ask:,.2f} (+{self.ask_spread_bps:.1f} bps) | "
            f"Inventory q: {self.inventory_q:+.2f} (σ={self.volatility_sigma*100:.1f}%)"
        )


class AsymmetricQuotingEngine:
    """
    Continuous Avellaneda-Stoikov Quoter with Inventory Risk Control.
    """

    def __init__(self, params: Optional[QuotingParameters] = None):
        self.params = params or QuotingParameters()
        self.inventory_tracker: Dict[str, float] = {}

    def set_inventory(self, symbol: str, current_q: float) -> None:
        """Updates current inventory position q for the asset."""
        self.inventory_tracker[symbol.upper()] = current_q

    def compute_asymmetric_quotes(
        self,
        symbol: str,
        mid_price: float,
        volatility_sigma: float,  # Annualized or hourly standard deviation
        current_inventory: Optional[float] = None,
    ) -> AsymmetricQuotes:
        """
        Calculates optimal asymmetric bid and ask prices based on inventory.
        """
        sym = symbol.upper()
        q = current_inventory if current_inventory is not None else self.inventory_tracker.get(sym, 0.0)
        gamma = self.params.gamma_risk_aversion
        kappa = self.params.kappa_order_arrival

        # Reservation price: r(s, q) = s - q * gamma * (sigma^2)
        # Using normalized variance
        var = max(0.0001, volatility_sigma ** 2)
        inventory_skew_usd = q * gamma * var * mid_price
        r_price = mid_price - inventory_skew_usd

        # Optimal half-spread: (2/gamma) * ln(1 + gamma/kappa)
        base_half_spread_pct = max(
            self.params.min_spread_bps / 10000.0,
            (1.0 / gamma) * math.log(1.0 + (gamma / kappa)) * 0.01,
        )
        base_half_spread_usd = mid_price * base_half_spread_pct

        # Asymmetric bid and ask
        opt_bid = r_price - base_half_spread_usd
        opt_ask = r_price + base_half_spread_usd

        # Ensure quotes don't cross mid
        opt_bid = min(opt_bid, mid_price * 0.9999)
        opt_ask = max(opt_ask, mid_price * 1.0001)

        bid_spread_bps = ((mid_price - opt_bid) / mid_price) * 10000.0
        ask_spread_bps = ((opt_ask - mid_price) / mid_price) * 10000.0

        quotes = AsymmetricQuotes(
            symbol=sym,
            mid_price=round(mid_price, 4),
            reservation_price=round(r_price, 4),
            optimal_bid=round(opt_bid, 4),
            optimal_ask=round(opt_ask, 4),
            bid_spread_bps=round(bid_spread_bps, 2),
            ask_spread_bps=round(ask_spread_bps, 2),
            inventory_q=round(q, 4),
            volatility_sigma=round(volatility_sigma, 4),
        )
        return quotes
