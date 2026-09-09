"""NEWS_CLOSE_IF_UNPROTECTED: flatten a live position when exchange TP+SL never attach."""
from __future__ import annotations

import pytest

from lighter_news_sniper import ActivePosition, MaxSizeExecutionEngine


def _pos() -> ActivePosition:
    return ActivePosition(
        position_id="p1",
        asset="ETH",
        market_index=0,
        side="BUY/LONG",
        entry_price=2000.0,
        size_eth=0.05,
        notional_usd=100.0,
        tp_pct=2.0,
        sl_pct=1.0,
    )


def _live_executor(monkeypatch) -> MaxSizeExecutionEngine:
    ex = MaxSizeExecutionEngine(is_live=False)
    ex.is_live = True  # bypass signer bootstrap; we stub the network methods below
    calls = {"cancel": [], "close": []}

    async def _cancel(market_index, ids):
        calls["cancel"].append((market_index, list(ids)))
        return True

    async def _close(pos, price, qty=None):
        calls["close"].append((pos.position_id, price, qty))
        return True

    monkeypatch.setattr(ex, "cancel_open_orders", _cancel)
    monkeypatch.setattr(ex, "close_position", _close)
    ex._test_calls = calls  # type: ignore[attr-defined]
    return ex


@pytest.mark.asyncio
async def test_missing_sl_closes_position_by_default(monkeypatch):
    monkeypatch.delenv("NEWS_CLOSE_IF_UNPROTECTED", raising=False)
    ex = _live_executor(monkeypatch)
    pos = _pos()
    ex.active_positions[pos.position_id] = pos

    # TP attached but SL did not — position is one-sided, must be flattened.
    closed = await ex._close_if_unprotected(pos, {"tp": True, "sl": False}, mark=2001.5)

    assert closed is True
    assert ex._test_calls["close"] == [("p1", 2001.5, None)]
    assert ex._test_calls["cancel"], "stray TP order must be cancelled before flattening"
    assert pos.is_active is False
    assert "p1" not in ex.active_positions


@pytest.mark.asyncio
async def test_both_attached_never_closes(monkeypatch):
    monkeypatch.delenv("NEWS_CLOSE_IF_UNPROTECTED", raising=False)
    ex = _live_executor(monkeypatch)
    pos = _pos()
    ex.active_positions[pos.position_id] = pos

    closed = await ex._close_if_unprotected(pos, {"tp": True, "sl": True}, mark=2001.5)

    assert closed is False
    assert ex._test_calls["close"] == []
    assert pos.is_active is True


@pytest.mark.asyncio
async def test_opt_out_keeps_position_with_local_watchdog(monkeypatch):
    monkeypatch.setenv("NEWS_CLOSE_IF_UNPROTECTED", "0")
    ex = _live_executor(monkeypatch)
    pos = _pos()
    ex.active_positions[pos.position_id] = pos

    closed = await ex._close_if_unprotected(pos, {"tp": False, "sl": False}, mark=2001.5)

    assert closed is False
    assert ex._test_calls["close"] == []
    assert "p1" in ex.active_positions


@pytest.mark.asyncio
async def test_paper_mode_never_closes(monkeypatch):
    monkeypatch.delenv("NEWS_CLOSE_IF_UNPROTECTED", raising=False)
    ex = _live_executor(monkeypatch)
    ex.is_live = False
    pos = _pos()

    closed = await ex._close_if_unprotected(pos, {"tp": False, "sl": False}, mark=2001.5)

    assert closed is False
    assert ex._test_calls["close"] == []


@pytest.mark.asyncio
async def test_price_falls_back_to_snapshot_then_entry(monkeypatch):
    monkeypatch.delenv("NEWS_CLOSE_IF_UNPROTECTED", raising=False)
    ex = _live_executor(monkeypatch)
    pos = _pos()

    async def _snap_fail(asset, market_index):
        raise RuntimeError("book unavailable")

    monkeypatch.setattr(ex, "fetch_market_snapshot", _snap_fail)
    closed = await ex._close_if_unprotected(pos, {"tp": False, "sl": False})

    assert closed is True
    # No mark, snapshot failed → entry price used so close_position still gets a usable price
    assert ex._test_calls["close"] == [("p1", 2000.0, None)]
