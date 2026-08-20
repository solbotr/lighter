from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, Sequence

from .config import Settings
from .domain import MarketSnapshot, PortfolioState
from .execution.paper import OrderIntent, PaperExecutor, PaperOrder
from .news import NewsEngine
from .news.models import NewsEvent
from .risk_engine import RiskGate, RiskLimits
from .signals.engine import SignalEngine

log = logging.getLogger(__name__)


class NewsProvider(Protocol):
    async def fetch(self) -> Sequence[NewsEvent]: ...


class MarketProvider(Protocol):
    async def snapshot(self, symbol: str) -> MarketSnapshot: ...


@dataclass(frozen=True)
class CycleSummary:
    events: int = 0
    signals: int = 0
    approved: int = 0
    rejected: int = 0
    orders: int = 0


@dataclass(frozen=True)
class RunSummary:
    iterations: int
    events: int
    signals: int
    approved: int
    rejected: int
    orders: int


class DemoNewsProvider:
    def __init__(self) -> None:
        self._sequence = 0

    async def fetch(self) -> Sequence[NewsEvent]:
        self._sequence += 1
        now = datetime.now(timezone.utc)
        return [
            NewsEvent(
                source="demo",
                title=f"Protocol partnership adoption update {self._sequence}",
                published_at=now,
                url="https://example.invalid/demo-news",
                entities=("BTC",),
                source_score=1.0,
            )
        ]


class DemoMarketProvider:
    async def snapshot(self, symbol: str) -> MarketSnapshot:
        now = datetime.now(timezone.utc)
        return MarketSnapshot(symbol, now, 99.95, 100.05, 100.0, 1_000_000.0, 0.05)


class PaperTradingLoop:
    def __init__(
        self,
        settings: Settings,
        news_provider: NewsProvider,
        market_provider: MarketProvider,
        *,
        symbol: str = "BTC",
        market_index: int = 1,
        executor: PaperExecutor | None = None,
    ) -> None:
        if settings.mode != "paper":
            raise ValueError("paper runtime requires LIGHTER_MODE=paper")
        self.settings = settings
        self.news_provider = news_provider
        self.market_provider = market_provider
        self.symbol = symbol
        self.market_index = market_index
        self.executor = executor or PaperExecutor()
        self.news_engine = NewsEngine(settings.news_max_age_seconds)
        self.signal_engine = SignalEngine(
            min_score=settings.min_signal_score,
            min_confidence=settings.min_confidence,
        )
        self.risk_gate = RiskGate(
            RiskLimits(
                max_position_notional=settings.max_position_notional,
                max_total_notional=settings.max_total_notional,
                max_daily_loss=settings.max_daily_loss,
                max_spread_bps=settings.max_spread_bps,
                max_volatility=settings.max_volatility,
            )
        )
        self.portfolio = PortfolioState(equity=1_000.0)

    async def run_iteration(self) -> CycleSummary:
        events = list(await self.news_provider.fetch())
        market = await self.market_provider.snapshot(self.symbol)
        self._validate_market(market)
        summary = CycleSummary(events=len(events))
        signals = 0
        approved = 0
        rejected = 0
        orders = 0
        for event in events:
            assessment = self.news_engine.assess(event)
            if assessment is None:
                continue
            signal = self.signal_engine.build(assessment, self.symbol)
            if signal is None or signal.expires_at <= datetime.now(timezone.utc):
                continue
            signals += 1
            decision = self.risk_gate.evaluate(signal, market, self.portfolio)
            if not decision.approved:
                rejected += 1
                log.info("paper risk rejection signal=%s reasons=%s", signal.signal_id, decision.reasons)
                continue
            approved += 1
            intent = OrderIntent(
                market_index=self.market_index,
                side="buy" if signal.direction.value == "long" else "sell",
                notional_usd=decision.max_notional,
                signal_id=signal.signal_id,
            )
            try:
                order = self.executor.submit(intent)
            except ValueError as exc:
                rejected += 1
                log.info("paper order rejected signal=%s reason=%s", signal.signal_id, exc)
                continue
            orders += 1
            self.portfolio.open_notional += order.intent.notional_usd
            self.portfolio.open_positions = len(self.executor.orders)
            log.info("paper order accepted id=%s symbol=%s side=%s notional=%.2f", order.order_id, self.symbol, intent.side, intent.notional_usd)
        return CycleSummary(len(events), signals, approved, rejected, orders)

    async def run(self, iterations: int = 0, interval_seconds: float | None = None) -> RunSummary:
        if iterations < 0:
            raise ValueError("iterations must not be negative")
        interval = self.settings.poll_interval_seconds if interval_seconds is None else interval_seconds
        if interval <= 0:
            raise ValueError("interval_seconds must be greater than zero")
        totals = RunSummary(0, 0, 0, 0, 0, 0)
        while iterations == 0 or totals.iterations < iterations:
            cycle = await self.run_iteration()
            totals = RunSummary(
                totals.iterations + 1,
                totals.events + cycle.events,
                totals.signals + cycle.signals,
                totals.approved + cycle.approved,
                totals.rejected + cycle.rejected,
                totals.orders + cycle.orders,
            )
            if iterations == 0 or totals.iterations < iterations:
                await asyncio.sleep(interval)
        return totals

    def _validate_market(self, market: MarketSnapshot) -> None:
        if market.symbol != self.symbol:
            raise ValueError("market symbol does not match configured symbol")
        if market.bid <= 0 or market.ask <= 0 or market.last <= 0 or market.ask < market.bid:
            raise ValueError("invalid market snapshot")
        age = (datetime.now(timezone.utc) - market.timestamp.astimezone(timezone.utc)).total_seconds()
        if age > self.settings.market_max_age_seconds:
            raise ValueError("market snapshot is stale")


async def run_demo(settings: Settings, iterations: int = 1) -> RunSummary:
    loop = PaperTradingLoop(settings, DemoNewsProvider(), DemoMarketProvider())
    return await loop.run(iterations=iterations)
