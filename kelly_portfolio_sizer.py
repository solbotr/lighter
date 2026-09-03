#!/usr/bin/env python3
"""
Fractional Kelly Position Sizer with Cross-Asset Correlation Adjustment (kelly_portfolio_sizer.py)
==================================================================================================
Upgrade 2: True Fractional Kelly Criterion + Correlation-Adjusted Sizing.

Implements:
1. True Fractional Kelly: f* = (b*p - q) / b * fraction
   where b = avg_win/avg_loss (odds ratio), p = win_rate, q = 1 - p.
2. Cross-asset correlation haircut: reduces sizing when correlated assets are already open,
   preventing hidden 2-3x portfolio risk from simultaneous SOL+LINK+ETH positions.
3. Integration hook for lighter_news_sniper.py calculate_max_order_size().
"""
from __future__ import annotations

import logging
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger("KellyPortfolioSizer")

# =============================================================================
# CORRELATION GROUPS
# Assets within a group are highly correlated; opening multiple simultaneously
# triggers a haircut to prevent hidden portfolio concentration.
# =============================================================================
_CORR_GROUPS: List[Tuple[FrozenSet[str], float]] = [
    (frozenset({"SOL", "ETH", "LINK", "XLM", "AVAX", "DOT", "OP", "ARB", "HYPE", "SUI"}), 0.78),  # L1/L2 crypto
    (frozenset({"BTC", "ETH", "SOL", "BNB", "XRP"}), 0.72),                                        # Blue-chip crypto
    (frozenset({"NVDA", "AMD", "ASML", "INTC", "QCOM"}), 0.68),                                    # Semiconductor
    (frozenset({"GOOGL", "META", "MSFT", "AMZN", "AAPL", "TSLA", "NFLX"}), 0.65),                 # Mega-cap tech
    (frozenset({"NATGAS", "WTI", "BRENTOIL"}), 0.70),                                              # Energy
    (frozenset({"XAU", "XAG", "XPT", "PAXG", "XAUT"}), 0.80),                                    # Precious metals
    (frozenset({"HOOD", "IBKR", "SCHW"}), 0.60),                                                   # Brokerages
    (frozenset({"PLTR", "RKLB", "SPCX"}), 0.55),                                                  # Defense/Space
]

# Conservative defaults — used before signal_outcomes accumulates sufficient history
_DEFAULT_WIN_RATE: float = 0.55   # 55% win rate prior
_DEFAULT_AVG_WIN: float  = 2.5    # 2.5% avg win (TP1)
_DEFAULT_AVG_LOSS: float = 1.2    # 1.2% avg loss (SL)
_DEFAULT_FRACTION: float = 0.25   # Quarter-Kelly for safety
_MAX_KELLY_FRACTION: float = 0.50 # Hard cap: never risk more than 50% of collateral


def fractional_kelly(
    win_rate: Optional[float] = None,
    avg_win_pct: Optional[float] = None,
    avg_loss_pct: Optional[float] = None,
    fraction: float = _DEFAULT_FRACTION,
) -> float:
    """
    Computes fractional Kelly position fraction (0.0 – 0.50).

    Kelly formula: f* = (b*p - q) / b
    where:
      b = avg_win_pct / avg_loss_pct  (odds ratio: payout per unit risked)
      p = win_rate
      q = 1 - p (loss probability)

    Returns the fraction of available collateral to risk on this trade.
    Scaled by `fraction` (default 0.25 = quarter-Kelly) for conservative risk management.
    """
    p = win_rate if win_rate is not None else _DEFAULT_WIN_RATE
    avg_win = avg_win_pct if avg_win_pct is not None else _DEFAULT_AVG_WIN
    avg_loss = avg_loss_pct if avg_loss_pct is not None else _DEFAULT_AVG_LOSS

    if avg_loss <= 0 or avg_win <= 0 or not (0.0 < p < 1.0):
        return 0.0

    b = avg_win / avg_loss           # odds ratio
    q = 1.0 - p
    kelly_full = (b * p - q) / b    # f* = (b*p - q) / b
    result = max(0.0, min(_MAX_KELLY_FRACTION, kelly_full * fraction))

    logger.debug(
        "[KELLY] p=%.3f b=%.2f f_full=%.3f fraction=%.2f → f_adj=%.3f",
        p, b, kelly_full, fraction, result,
    )
    return result


def correlation_haircut(
    open_assets: Set[str],
    new_asset: str,
) -> float:
    """
    Returns a sizing multiplier [0.30 – 1.00] based on how many already-open positions
    are in the same high-correlation group as the new asset.

    Haircut tiers:
      1 correlated open → 0.65× multiplier
      2 correlated open → 0.45× multiplier
      3+ correlated open → 0.30× multiplier
    """
    sym = new_asset.upper()
    open_upper = {s.upper() for s in open_assets}

    for group, corr in _CORR_GROUPS:
        if sym in group:
            overlap_count = len(open_upper & group)
            if overlap_count >= 3:
                multiplier = max(0.30, 1.0 - corr * 1.2)
            elif overlap_count == 2:
                multiplier = max(0.45, 1.0 - corr * 0.8)
            elif overlap_count == 1:
                multiplier = max(0.65, 1.0 - corr * 0.4)
            else:
                multiplier = 1.0  # No overlap — no haircut

            if overlap_count > 0:
                logger.info(
                    "[KELLY HAIRCUT] %s | %d correlated positions open (ρ=%.2f) → size ×%.2f",
                    sym, overlap_count, corr, multiplier,
                )
            return round(multiplier, 4)

    return 1.0  # Uncorrelated asset — full sizing


def kelly_adjusted_usd(
    base_usd: float,
    max_usd: float,
    collateral_usd: float,
    open_assets: Optional[Set[str]] = None,
    new_asset: str = "",
    win_rate: Optional[float] = None,
    avg_win_pct: Optional[float] = None,
    avg_loss_pct: Optional[float] = None,
    fraction: float = _DEFAULT_FRACTION,
) -> float:
    """
    Main integration entry point.
    Returns Kelly + correlation-adjusted USD position size, clamped to [base_usd, max_usd].

    Args:
        base_usd:       Minimum position size (always execute at least this much)
        max_usd:        Maximum position size (high-conviction cap)
        collateral_usd: Available margin / collateral in USD
        open_assets:    Set of currently open position symbols
        new_asset:      Symbol being considered for entry
        win_rate:       Historical win rate (0.0–1.0). Uses prior if None.
        avg_win_pct:    Average winner size as % of notional. Uses prior if None.
        avg_loss_pct:   Average loser size as % of notional. Uses prior if None.
        fraction:       Kelly fraction (default 0.25 = quarter-Kelly)
    """
    frac = fractional_kelly(
        win_rate=win_rate,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        fraction=fraction,
    )
    kelly_usd = collateral_usd * frac
    haircut = correlation_haircut(open_assets or set(), new_asset)
    adjusted = kelly_usd * haircut

    # Clamp: never below base_usd (always take at least baseline size), never above max_usd
    result = max(base_usd, min(max_usd, adjusted))

    logger.info(
        "[KELLY SIZER] %s | f=%.3f × $%.2f collateral = $%.2f raw | haircut=×%.2f → $%.2f | clamped=$%.2f",
        new_asset or "?", frac, collateral_usd, kelly_usd, haircut, adjusted, result,
    )
    return round(result, 2)
