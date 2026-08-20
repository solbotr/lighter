from __future__ import annotations

from dataclasses import dataclass

from .models import Direction, MarketSnapshot, RiskDecision, Signal, TradeIntent


@dataclass(frozen=True)
class RiskLimits:
    max_position_usd: float = 100.0
    max_daily_loss_usd: float = 25.0
    max_open_positions: int = 3
    max_leverage: float = 2.0
    max_spread_bps: float = 30.0
    max_slippage_bps: float = 20.0
    min_liquidity_usd: float = 25_000.0
    min_signal_score: float = 0.75
    max_news_age_seconds: int = 120


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()
        self.daily_pnl = 0.0
        self.open_positions = 0
        self.kill_switch = False

    def evaluate(self, signal: Signal, market: MarketSnapshot, requested_notional: float) -> RiskDecision:
        if self.kill_switch:
            return RiskDecision(approved=False, reason="kill switch active")
        if signal.score < self.limits.min_signal_score:
            return RiskDecision(approved=False, reason=f"signal score {signal.score:.3f} below threshold")
        if self.daily_pnl <= -self.limits.max_daily_loss_usd:
            return RiskDecision(approved=False, reason="daily loss limit reached")
        if self.open_positions >= self.limits.max_open_positions:
            return RiskDecision(approved=False, reason="max open positions reached")
        if market.spread_bps > self.limits.max_spread_bps:
            return RiskDecision(approved=False, reason="spread too wide")
        if market.liquidity_usd < self.limits.min_liquidity_usd:
            return RiskDecision(approved=False, reason="insufficient liquidity")
        notional = min(requested_notional, self.limits.max_position_usd)
        if notional <= 0:
            return RiskDecision(approved=False, reason="invalid notional")
        if signal.priced_in_penalty >= 0.9:
            return RiskDecision(approved=False, reason="move appears already priced in")
        return RiskDecision(
            approved=True,
            reason="risk checks passed",
            notional_usd=notional,
            max_loss_usd=min(self.limits.max_position_usd * 0.02, self.limits.max_daily_loss_usd),
            max_slippage_bps=self.limits.max_slippage_bps,
        )

    def intent(self, signal: Signal, decision: RiskDecision) -> TradeIntent:
        if not decision.approved:
            raise ValueError(decision.reason)
        return TradeIntent(
            symbol=signal.symbol,
            direction=signal.direction,
            notional_usd=decision.notional_usd,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            max_slippage_bps=decision.max_slippage_bps,
            signal_score=signal.score,
        )
