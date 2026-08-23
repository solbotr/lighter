#!/usr/bin/env python3
"""
Binance L3 Pre-Emptive Repricing Arbitrage (binance_lead_repricer.py)
====================================================================
Monitors high-frequency Binance Perpetual trades (< 10ms WebSocket latency).
When aggressive whale sweeps or sudden price dislocations occur on Binance,
it front-runs stale resting maker quotes on zkLighter before other market makers can cancel.

Formula:
  Dislocation_bps = ((Binance_Mid - Lighter_Ask) / Lighter_Ask) * 10,000 (for Long arb)
  Dislocation_bps = ((Lighter_Bid - Binance_Mid) / Lighter_Bid) * 10,000 (for Short arb)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("BinanceLeadRepricer")


@dataclass
class BinanceTradeSweep:
    symbol: str
    price: float
    volume_usd: float
    side: str  # "BUY" or "SELL"
    timestamp: float = field(default_factory=time.time)


@dataclass
class RepricingArbOpportunity:
    opportunity_id: str
    symbol: str
    direction: str  # "TAKE_ASK_LONG" or "TAKE_BID_SHORT"
    binance_price: float
    lighter_stale_price: float
    dislocation_bps: float
    estimated_profit_usd: float
    is_executable: bool = True
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"⚡ [BINANCE REPRICING ARB] {self.direction} on {self.symbol} | "
            f"Binance: ${self.binance_price:,.2f} vs zkLighter Stale: ${self.lighter_stale_price:,.2f} | "
            f"Dislocation: +{self.dislocation_bps:.1f} bps (Est Profit: ${self.estimated_profit_usd:,.2f} USD)"
        )


class BinanceLeadRepricingEngine:
    """
    Sub-10ms Lead-Lag Stale Quote Exploitation Engine.
    """

    def __init__(
        self,
        min_dislocation_bps: float = 12.0,  # 12 bps (0.12%) min threshold
        min_sweep_volume_usd: float = 50000.0,
        max_quote_age_ms: float = 250.0,
    ):
        self.min_dislocation_bps = min_dislocation_bps
        self.min_sweep_volume_usd = min_sweep_volume_usd
        self.max_quote_age_ms = max_quote_age_ms
        self.binance_latest_prices: Dict[str, float] = {}
        self.active_opportunities: Dict[str, RepricingArbOpportunity] = {}
        self.total_arbitrage_executed_usd = 0.0

    def on_binance_trade_tick(
        self,
        symbol: str,
        price: float,
        volume_usd: float,
        side: str,
    ) -> Optional[RepricingArbOpportunity]:
        """Ingests raw Binance trade tick and updates reference mark."""
        sym = symbol.upper()
        self.binance_latest_prices[sym] = price
        return None

    def evaluate_stale_quotes(
        self,
        symbol: str,
        lighter_best_bid: float,
        lighter_best_ask: float,
        available_capital_usd: float = 150.0,
    ) -> Optional[RepricingArbOpportunity]:
        """
        Compares live Binance leading price against zkLighter resting orderbook.
        """
        sym = symbol.upper()
        binance_px = self.binance_latest_prices.get(sym)
        if not binance_px or lighter_best_ask <= 0 or lighter_best_bid <= 0:
            return None

        # 1. Check Long Arb: Binance broke upward, zkLighter ask is still cheap
        if binance_px > lighter_best_ask:
            dislocation_bps = ((binance_px - lighter_best_ask) / lighter_best_ask) * 10000.0
            if dislocation_bps >= self.min_dislocation_bps:
                profit_est = (dislocation_bps / 10000.0) * available_capital_usd
                opp_id = f"arb_long_{sym}_{int(time.time()*1000)}"
                opp = RepricingArbOpportunity(
                    opportunity_id=opp_id,
                    symbol=sym,
                    direction="TAKE_ASK_LONG",
                    binance_price=binance_px,
                    lighter_stale_price=lighter_best_ask,
                    dislocation_bps=round(dislocation_bps, 2),
                    estimated_profit_usd=round(profit_est, 2),
                )
                self.active_opportunities[opp_id] = opp
                logger.info(opp.summary())
                return opp

        # 2. Check Short Arb: Binance broke downward, zkLighter bid is still high
        elif binance_px < lighter_best_bid:
            dislocation_bps = ((lighter_best_bid - binance_px) / lighter_best_bid) * 10000.0
            if dislocation_bps >= self.min_dislocation_bps:
                profit_est = (dislocation_bps / 10000.0) * available_capital_usd
                opp_id = f"arb_short_{sym}_{int(time.time()*1000)}"
                opp = RepricingArbOpportunity(
                    opportunity_id=opp_id,
                    symbol=sym,
                    direction="TAKE_BID_SHORT",
                    binance_price=binance_px,
                    lighter_stale_price=lighter_best_bid,
                    dislocation_bps=round(dislocation_bps, 2),
                    estimated_profit_usd=round(profit_est, 2),
                )
                self.active_opportunities[opp_id] = opp
                logger.info(opp.summary())
                return opp

        return None
