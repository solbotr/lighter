from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioLimits:
    max_gross_notional: float = 250.0
    max_net_notional: float = 250.0
    max_asset_notional: float = 100.0
    max_leverage: float = 2.0
    min_margin_ratio: float = 0.20


@dataclass(frozen=True)
class PortfolioCheck:
    approved: bool
    reasons: tuple[str, ...]
    allowed_notional: float


def check_portfolio(
    current_gross: float,
    current_net: float,
    proposed_notional: float,
    equity: float,
    margin_used: float,
    asset_notional: float,
    limits: PortfolioLimits,
) -> PortfolioCheck:
    failures: list[str] = []
    if proposed_notional <= 0:
        failures.append("non_positive_notional")
    gross = current_gross + proposed_notional
    if gross > limits.max_gross_notional:
        failures.append("gross_exposure_limit")
    if abs(current_net + proposed_notional) > limits.max_net_notional:
        failures.append("net_exposure_limit")
    if asset_notional + proposed_notional > limits.max_asset_notional:
        failures.append("asset_concentration_limit")
    if equity <= 0:
        failures.append("invalid_equity")
    else:
        leverage = gross / equity
        if leverage > limits.max_leverage:
            failures.append("leverage_limit")
        margin_ratio = max(0.0, 1.0 - margin_used / equity)
        if margin_ratio < limits.min_margin_ratio:
            failures.append("margin_floor")
    allowed = max(0.0, min(limits.max_gross_notional - current_gross, limits.max_asset_notional - asset_notional))
    return PortfolioCheck(not failures, tuple(failures), allowed)
