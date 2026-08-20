from __future__ import annotations

from dataclasses import dataclass

from .domain import MarketSnapshot, PortfolioState, RiskDecision, Signal


@dataclass(frozen=True)
class RiskLimits:
    max_position_notional: float = 100.0
    max_total_notional: float = 250.0
    max_daily_loss: float = 25.0
    max_consecutive_losses: int = 3
    max_open_positions: int = 3
    max_spread_bps: float = 50.0
    max_volatility: float = 0.25


class RiskGate:
    def __init__(self, limits: RiskLimits) -> None:
        self.limits = limits

    def evaluate(
        self, signal: Signal, market: MarketSnapshot, portfolio: PortfolioState
    ) -> RiskDecision:
        failures: list[str] = []
        if portfolio.halted:
            failures.append("portfolio_halted")
        if signal.score < 0.75 or signal.confidence < 0.70:
            failures.append("signal_below_threshold")
        if market.spread_bps > self.limits.max_spread_bps:
            failures.append("spread_too_wide")
        if market.volatility > self.limits.max_volatility:
            failures.append("volatility_too_high")
        if portfolio.daily_pnl <= -abs(self.limits.max_daily_loss):
            failures.append("daily_loss_limit")
        if portfolio.consecutive_losses >= self.limits.max_consecutive_losses:
            failures.append("loss_streak_limit")
        if portfolio.open_positions >= self.limits.max_open_positions:
            failures.append("position_count_limit")
        remaining = max(0.0, self.limits.max_total_notional - portfolio.open_notional)
        notional = min(self.limits.max_position_notional, remaining)
        if notional <= 0:
            failures.append("exposure_limit")
        return RiskDecision(approved=not failures, reasons=tuple(failures), max_notional=notional)
