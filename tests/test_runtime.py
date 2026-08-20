from datetime import datetime, timezone

import pytest

from lighter_trader.config import Settings
from lighter_trader.domain import MarketSnapshot
from lighter_trader.news.models import NewsEvent
from lighter_trader.runtime import DemoMarketProvider, PaperTradingLoop


class OneEventProvider:
    async def fetch(self):
        return [
            NewsEvent(
                source="test",
                title="Protocol partnership adoption approved",
                published_at=datetime.now(timezone.utc),
                entities=("BTC",),
                source_score=1.0,
            )
        ]


class WideMarketProvider:
    async def snapshot(self, symbol):
        now = datetime.now(timezone.utc)
        return MarketSnapshot(symbol, now, 99.0, 101.0, 100.0, 1000.0, 0.05)


@pytest.mark.asyncio
async def test_paper_loop_submits_once():
    loop = PaperTradingLoop(Settings(), OneEventProvider(), DemoMarketProvider())
    summary = await loop.run(iterations=1)
    assert summary.orders == 1
    assert len(loop.executor.orders) == 1


@pytest.mark.asyncio
async def test_duplicate_event_is_not_submitted_twice():
    provider = OneEventProvider()
    loop = PaperTradingLoop(Settings(), provider, DemoMarketProvider())
    first = await loop.run_iteration()
    second = await loop.run_iteration()
    assert first.orders == 1
    assert second.orders == 0
    assert len(loop.executor.orders) == 1


@pytest.mark.asyncio
async def test_wide_market_is_rejected():
    loop = PaperTradingLoop(Settings(), OneEventProvider(), WideMarketProvider())
    summary = await loop.run(iterations=1)
    assert summary.orders == 0
    assert summary.rejected == 1
