from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskLimits:
    max_position_usd: float = 100.0
    max_daily_loss_usd: float = 25.0
    max_open_positions: int = 3
    max_leverage: float = 2.0


@dataclass(frozen=True)
class AccountState:
    equity_usd: float
    daily_pnl_usd: float
    open_positions: int
    proposed_notional_usd: float
    proposed_leverage: float


def allow_trade(state: AccountState, limits: RiskLimits, signal_score: float) -> tuple[bool, str]:
    if signal_score < 0.75:
        return False, "signal below threshold"
    if state.proposed_notional_usd <= 0 or state.proposed_notional_usd > limits.max_position_usd:
        return False, "position limit"
    if state.daily_pnl_usd <= -abs(limits.max_daily_loss_usd):
        return False, "daily loss limit"
    if state.open_positions >= limits.max_open_positions:
        return False, "open-position limit"
    if state.proposed_leverage <= 0 or state.proposed_leverage > limits.max_leverage:
        return False, "leverage limit"
    if state.equity_usd <= 0:
        return False, "invalid equity"
    return True, "risk checks passed"
