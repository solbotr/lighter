#!/usr/bin/env python3
"""
Unit & Integration Tests for Lighter DEX Market Maker Bot
=========================================================
Tests:
- Avellaneda-Stoikov & GLFT quantitative strategy calculations
- Micro-price and OFI alpha indicators
- Risk Manager limits, price bands, and circuit breakers
- Queue-preserving Deadband OMS order diffing
- Live execution via mocked signer/exchange (no paper mode)
- SQLite analytics, volume aggregation, and reward points estimation
"""

import os
import sys
import time
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from lighter_strategy import (
    AvellanedaStoikovQuoter,
    L2OrderBook,
    OrderBookLevel,
    OrderSide,
    TargetQuote,
)
from lighter_risk_manager import LighterRiskManager, RiskLimits
from lighter_execution import (
    ActiveOrder,
    DeadbandOMS,
)
from lighter_db import LighterDBManager


def make_test_book(mid: float = 3000.0, spread: float = 0.5) -> L2OrderBook:
    """Helper to build a mock Level-2 orderbook."""
    best_bid = mid - (spread / 2.0)
    best_ask = mid + (spread / 2.0)
    return L2OrderBook(
        market_index=0,
        bids=[
            OrderBookLevel(price=best_bid, size=1.5),
            OrderBookLevel(price=best_bid - 0.1, size=2.0),
            OrderBookLevel(price=best_bid - 0.2, size=5.0),
        ],
        asks=[
            OrderBookLevel(price=best_ask, size=1.0),
            OrderBookLevel(price=best_ask + 0.1, size=2.5),
            OrderBookLevel(price=best_ask + 0.2, size=4.0),
        ],
        nonce=100,
    )


# =============================================================================
# 1. STRATEGY ENGINE TESTS
# =============================================================================

def test_micro_price_calculation():
    quoter = AvellanedaStoikovQuoter()
    # Imbalanced book: Bids (size 3.0 @ 3000.0), Asks (size 1.0 @ 3001.0)
    book = L2OrderBook(
        market_index=0,
        bids=[OrderBookLevel(price=3000.0, size=3.0)],
        asks=[OrderBookLevel(price=3001.0, size=1.0)],
    )
    # S_micro = (3.0 * 3001.0 + 1.0 * 3000.0) / 4.0 = (9003 + 3000) / 4 = 3000.75
    micro_p = quoter.calculate_micro_price(book)
    assert pytest.approx(micro_p, 0.001) == 3000.75
    assert micro_p > book.mid_price  # More bid volume pushes micro-price up


def test_ofi_calculation():
    quoter = AvellanedaStoikovQuoter()
    book1 = L2OrderBook(
        market_index=0,
        bids=[OrderBookLevel(price=3000.0, size=2.0)],
        asks=[OrderBookLevel(price=3001.0, size=2.0)],
    )
    # Book2 has higher bid size (buying queue increase)
    book2 = L2OrderBook(
        market_index=0,
        bids=[OrderBookLevel(price=3000.0, size=5.0)],
        asks=[OrderBookLevel(price=3001.0, size=2.0)],
    )
    ofi = quoter.calculate_ofi(book1, book2)
    assert ofi == 3.0  # +3.0 net bid increase


def test_avellaneda_stoikov_inventory_skew():
    quoter = AvellanedaStoikovQuoter(gamma=0.05, phi=0.02, volatility=0.02)
    fair_price = 3000.0

    # Neutral inventory
    r_neutral = quoter.calculate_reservation_price(fair_price, inventory_q=0.0)
    assert r_neutral == fair_price

    # Long inventory (q = +1.0) -> reservation price lower (wants to sell)
    r_long = quoter.calculate_reservation_price(fair_price, inventory_q=1.0)
    assert r_long < fair_price

    # Short inventory (q = -1.0) -> reservation price higher (wants to buy)
    r_short = quoter.calculate_reservation_price(fair_price, inventory_q=-1.0)
    assert r_short > fair_price


def test_generate_quotes_multi_layer_properties():
    quoter = AvellanedaStoikovQuoter(num_layers=3, base_size=0.1, tick_size=0.01)
    book = make_test_book(mid=3000.0, spread=0.2)

    quotes = quoter.generate_quotes(book=book, inventory_q=0.0)
    assert OrderSide.BUY in quotes
    assert OrderSide.SELL in quotes
    assert len(quotes[OrderSide.BUY]) == 3
    assert len(quotes[OrderSide.SELL]) == 3

    # Check bids are descending in price
    bids = quotes[OrderSide.BUY]
    for i in range(len(bids) - 1):
        assert bids[i].price > bids[i + 1].price
        assert bids[i].price < book.best_ask  # Non-crossing post-only

    # Check asks are ascending in price
    asks = quotes[OrderSide.SELL]
    for i in range(len(asks) - 1):
        assert asks[i].price < asks[i + 1].price
        assert asks[i].price > book.best_bid  # Non-crossing post-only

    # Top bid must be strictly less than Top ask
    assert bids[0].price < asks[0].price


# =============================================================================
# 2. RISK MANAGER & CIRCUIT BREAKER TESTS
# =============================================================================

def test_risk_manager_price_band_filter():
    limits = RiskLimits(max_price_deviation_pct=0.015)  # +/- 1.5%
    rm = LighterRiskManager(limits=limits)
    mid_price = 3000.0

    quotes = {
        OrderSide.BUY: [
            TargetQuote(side=OrderSide.BUY, price=2995.0, size=0.1, layer=0),
            TargetQuote(side=OrderSide.BUY, price=2800.0, size=0.1, layer=1),  # Out of bounds (-6.6%)
        ],
        OrderSide.SELL: [
            TargetQuote(side=OrderSide.SELL, price=3005.0, size=0.1, layer=0),
            TargetQuote(side=OrderSide.SELL, price=3200.0, size=0.1, layer=1),  # Out of bounds (+6.6%)
        ],
    }

    validated = rm.validate_quotes(quotes, mid_price=mid_price)
    assert len(validated[OrderSide.BUY]) == 1
    assert validated[OrderSide.BUY][0].price == 2995.0
    assert len(validated[OrderSide.SELL]) == 1
    assert validated[OrderSide.SELL][0].price == 3005.0


def test_risk_manager_hard_inventory_limit():
    limits = RiskLimits(max_inventory=1.0)
    rm = LighterRiskManager(limits=limits)
    rm.set_inventory(1.0)  # Max long reached

    quotes = {
        OrderSide.BUY: [TargetQuote(side=OrderSide.BUY, price=2990.0, size=0.1, layer=0)],
        OrderSide.SELL: [TargetQuote(side=OrderSide.SELL, price=3010.0, size=0.1, layer=0)],
    }

    validated = rm.validate_quotes(quotes, mid_price=3000.0)
    # Buy quotes must be blocked completely
    assert len(validated[OrderSide.BUY]) == 0
    # Sell quotes must still be active to shed position
    assert len(validated[OrderSide.SELL]) == 1


def test_risk_manager_daily_loss_limit_auto_pause():
    limits = RiskLimits(max_daily_loss_usd=50.0)
    rm = LighterRiskManager(limits=limits)

    # Small loss
    rm.update_pnl(-20.0, fill_volume_usd=500.0)
    assert not rm.is_paused

    # Breach loss limit (-60.0 total)
    rm.update_pnl(-40.0, fill_volume_usd=500.0)
    assert rm.is_paused
    assert "Daily loss limit breached" in rm.pause_reason

    # Quotes should now be blocked
    quotes = {
        OrderSide.BUY: [TargetQuote(side=OrderSide.BUY, price=2990.0, size=0.1, layer=0)],
        OrderSide.SELL: [TargetQuote(side=OrderSide.SELL, price=3010.0, size=0.1, layer=0)],
    }
    validated = rm.validate_quotes(quotes, mid_price=3000.0)
    assert len(validated[OrderSide.BUY]) == 0
    assert len(validated[OrderSide.SELL]) == 0


# =============================================================================
# 3. DEADBAND OMS TESTS
# =============================================================================

def test_deadband_oms_preserves_queue_position():
    oms = DeadbandOMS(price_deadband_ticks=2, size_drift_pct=0.20)
    tick_size = 0.01

    # Place initial order with fresh timestamp
    oms.register_order(
        ActiveOrder(
            client_order_id=101,
            order_id="ord_101",
            side=OrderSide.BUY,
            price=2999.00,
            size=0.10,
            layer=0,
            timestamp=time.time(),
        )
    )

    # New target quote differs by only 1 tick (within 2-tick deadband) and same size
    targets = {
        OrderSide.BUY: [TargetQuote(side=OrderSide.BUY, price=2999.01, size=0.10, layer=0)],
        OrderSide.SELL: [],
    }

    cancels, placements = oms.compute_diff(targets, tick_size=tick_size)
    # Order should be preserved (no cancel, no new placement)
    assert len(cancels) == 0
    assert len(placements) == 0


def test_deadband_oms_replaces_when_exceeding_deadband():
    oms = DeadbandOMS(price_deadband_ticks=2, size_drift_pct=0.20)
    tick_size = 0.01

    oms.register_order(
        ActiveOrder(
            client_order_id=101,
            order_id="ord_101",
            side=OrderSide.BUY,
            price=2999.00,
            size=0.10,
            layer=0,
            timestamp=time.time(),
        )
    )

    # New target quote moved by 5 ticks (exceeds 2-tick deadband)
    targets = {
        OrderSide.BUY: [TargetQuote(side=OrderSide.BUY, price=2999.05, size=0.10, layer=0)],
        OrderSide.SELL: [],
    }

    cancels, placements = oms.compute_diff(targets, tick_size=tick_size)
    assert cancels == [101]
    assert len(placements) == 1
    assert placements[0].price == 2999.05


# =============================================================================
# 4. LIVE FILL / OMS TESTS
# =============================================================================

def test_oms_registers_and_clears_live_orders():
    oms = DeadbandOMS()
    oms.register_order(
        ActiveOrder(
            client_order_id=101,
            order_id="live_101",
            side=OrderSide.BUY,
            price=3000.00,
            size=1.0,
            layer=0,
            timestamp=1000.0,
        )
    )
    assert 101 in oms.active_orders
    oms.remove_order(101)
    assert 101 not in oms.active_orders
    oms.register_order(
        ActiveOrder(
            client_order_id=102,
            order_id="live_102",
            side=OrderSide.SELL,
            price=3002.00,
            size=1.0,
            layer=0,
            timestamp=1005.0,
        )
    )
    oms.clear_all()
    assert oms.active_orders == {}


# =============================================================================
# 5. SQLITE PERSISTENCE & CAMPAIGN POINTS TESTS
# =============================================================================

def test_db_manager_volume_and_points_calculation():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        db = LighterDBManager(db_path=db_path)

        # Record a buy fill ($1.5M volume)
        db.record_fill(
            market_index=0,
            order_id="ord_1",
            client_order_id="c_1",
            side="BUY",
            price=3000.0,
            size=500.0,
            usd_value=1_500_000.0,
            realized_pnl=0.0,
            is_maker=True,
        )

        # Record a sell fill ($1.5M volume, +$50 PnL)
        db.record_fill(
            market_index=0,
            order_id="ord_2",
            client_order_id="c_2",
            side="SELL",
            price=3000.1,
            size=500.0,
            usd_value=1_500_050.0,
            realized_pnl=50.0,
            is_maker=True,
        )

        stats = db.get_stats(market_index=0)
        assert stats["total_fills"] == 2
        assert stats["buy_fills"] == 1
        assert stats["sell_fills"] == 1
        assert pytest.approx(stats["total_volume_usd"], 1.0) == 3_000_050.0
        assert stats["total_realized_pnl_usd"] == 50.0
        # 4.0 points per $1M -> ~$12.00 points for $3M volume
        assert pytest.approx(stats["estimated_points"], 0.1) == 12.00
        # 1 winning trade (+50), 1 breakeven (0) -> 100% win rate on closed trades with non-zero pnl
        assert stats["winning_trades"] == 1
        assert stats["losing_trades"] == 0
        assert stats["win_rate_pct"] == 100.0

    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


def test_db_manager_win_rate_and_daily_stats():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        db = LighterDBManager(db_path=db_path)

        # Record 3 winning trades and 1 losing trade
        db.record_fill(market_index=0, order_id="1", client_order_id="1", side="SELL", price=3010, size=1, usd_value=3010, realized_pnl=10.0)
        db.record_fill(market_index=0, order_id="2", client_order_id="2", side="SELL", price=3020, size=1, usd_value=3020, realized_pnl=20.0)
        db.record_fill(market_index=0, order_id="3", client_order_id="3", side="SELL", price=3015, size=1, usd_value=3015, realized_pnl=15.0)
        db.record_fill(market_index=0, order_id="4", client_order_id="4", side="SELL", price=2980, size=1, usd_value=2980, realized_pnl=-20.0)

        daily = db.get_daily_stats(market_index=0)
        assert daily["daily_fills"] == 4
        assert daily["daily_winning_trades"] == 3
        assert daily["daily_losing_trades"] == 1
        # Win rate: 3 wins / 4 total closed = 75.0%
        assert daily["daily_win_rate_pct"] == 75.0
        assert daily["daily_realized_pnl_usd"] == 25.0
        assert daily["daily_volume_usd"] == 12025.0
        assert daily["all_time_volume_usd"] == 12025.0

    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


# =============================================================================
# 6. TELEGRAM DAILY REPORT & HYBRID ENGINE TESTS
# =============================================================================

def test_telegram_daily_pnl_report_formatting():
    from lighter_telegram import format_daily_pnl_report

    mock_stats = {
        "daily_realized_pnl_usd": 142.50,
        "daily_net_pnl_usd": 145.20,
        "daily_volume_usd": 500_000.0,
        "daily_win_rate_pct": 80.0,
        "daily_winning_trades": 8,
        "daily_losing_trades": 2,
        "daily_points": 2.0000,
        "daily_fills": 10,
        "daily_buy_fills": 5,
        "daily_sell_fills": 5,
        "all_time_volume_usd": 1_500_000.0,
        "all_time_pnl_usd": 350.0,
        "all_time_points": 6.0000,
    }

    report = format_daily_pnl_report(mock_stats)
    assert "LIGHTER DAILY PnL & VOLUME REPORT" in report
    assert "+$145.20 USD" in report
    assert "80.0%" in report
    assert "8W / 2L" in report
    assert "$500,000.00 USD" in report
    assert "+2.0000 pts" in report
    assert "LIVE zkLighter" in report
    assert "PAPER" not in report


@pytest.mark.asyncio
async def test_telegram_report_command():
    from lighter_telegram import LighterTelegramBot

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        db = LighterDBManager(db_path=db_path)
        db.record_fill(market_index=0, order_id="1", client_order_id="1", side="BUY", price=2500, size=1, usd_value=2500, realized_pnl=50.0)

        bot = LighterTelegramBot(
            bot_context={
                "db": db,
            }
        )

        msg, kb = await bot.handle_user_action("/report", user_id=999)
        assert "LIGHTER DAILY PnL & VOLUME REPORT" in msg
        assert "2500" in msg or "2,500.00" in msg
        assert kb is not None
        assert any(btn.get("callback_data") == "menu_report" for row in kb.get("inline_keyboard", []) for btn in row)

    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


def _attach_mock_signer(engine):
    engine.signer_failed = False
    signer = MagicMock()
    signer.create_order = AsyncMock(return_value=("tx", "0xabc", None))
    signer.cancel_order = AsyncMock(return_value=("tx", "0xabc", None))
    signer.cancel_all_orders = AsyncMock(return_value=("tx", "0xabc", None))
    signer.ORDER_TYPE_MARKET = 1
    signer.ORDER_TIME_IN_FORCE_IOC = 1
    engine.signer_client = signer
    return signer


@pytest.mark.asyncio
async def test_execution_engine_taker_snipe():
    from lighter_execution import LighterExecutionEngine

    engine = LighterExecutionEngine(market_index=0, account_index=737649, api_private_key="test-key")
    _attach_mock_signer(engine)
    result = await engine.execute_taker_snipe(
        side=OrderSide.BUY,
        price=2650.0,
        size=0.1,
        reason="TEST_SNIPE",
    )

    assert result["success"] is True
    assert result["side"] == "BUY"
    assert result["price"] == 2650.0
    assert result["size"] == 0.1
    assert result["is_maker"] is False
    assert result["mode"] == "LIVE"
    engine.signer_client.create_order.assert_awaited()


def test_ws_streamer_tracks_book_age():
    from lighter_execution import LighterWebSocketStreamer

    streamer = LighterWebSocketStreamer(market_index=0)
    assert streamer.last_update_ts == 0.0
    assert streamer.book_age_ms() == float("inf")
    streamer.mark_book_update(time.time())
    assert streamer.last_update_ts > 0
    assert streamer.book_age_ms() < 100.0


async def _wire_mm_execution_mocks(bot):
    async def fake_diff(cancels, placements):
        for cid in cancels:
            bot.execution.oms.remove_order(cid)
        for quote in placements:
            cid = bot.execution.get_next_client_order_id()
            bot.execution.oms.register_order(
                ActiveOrder(
                    client_order_id=cid,
                    order_id=f"mock_{cid}",
                    side=quote.side,
                    price=quote.price,
                    size=quote.size,
                    layer=quote.layer,
                    timestamp=time.time(),
                )
            )
        return len(cancels), len(placements)

    async def fake_cancel_all():
        n = len(bot.execution.oms.active_orders)
        bot.execution.oms.clear_all()
        return n

    bot.execution.execute_diff = fake_diff
    bot.execution.cancel_all_orders = fake_cancel_all
    bot.execution.execute_taker_snipe = AsyncMock(
        return_value={"success": True, "mode": "LIVE", "side": "BUY", "size": 0.2}
    )
    bot.risk_manager.record_heartbeat()
    return bot


@pytest.mark.asyncio
async def test_hybrid_quoting_engine_instant_catalyst_switch(monkeypatch):
    from lighter_mm_bot import LighterMarketMakerBot
    from lighter_news_sniper import CatalystSignal

    monkeypatch.setenv("ADMIN_CHAT_ID", "999001")
    monkeypatch.setenv("NEWS_KILL_SWITCH", "false")
    monkeypatch.delenv("NEWS_KILL_SWITCH", raising=False)
    # Synthetic classifier-only catalyst (no upstream feed event) must be live-eligible for this test
    monkeypatch.setenv("NEWS_LIVE_SOURCE_IDS", "mm_catalyst")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        bot = LighterMarketMakerBot(
            market_index=0,
            base_size=0.1,
            db_path=db_path,
            enable_telegram=False,
            enable_hybrid=True,
            catalyst_cooldown_sec=5.0,
        )
        bot._reconcile_every_n_cycles = 10_000
        bot._max_book_age_ms = 2000.0
        await _wire_mm_execution_mocks(bot)
        bot._fetch_mm_collateral_usd = AsyncMock(return_value=500.0)

        # 1. Quiet Period: Maker quotes placed on orderbook
        book = make_test_book(mid=3000.0, spread=1.0)
        bot.current_book = book
        bot._record_book_update(book)
        await bot._process_quoting_cycle(book)

        active_count = len(bot.execution.oms.active_orders)
        assert active_count > 0
        assert bot.engine_state == "MAKER_QUOTING"

        # 2. Instant Catalyst Switch: Breaking news signal arrives
        signal = CatalystSignal(
            news_id="test_cat_1",
            headline="Donald Trump announces national strategic ETH reserve",
            target_asset="ETH",
            market_index=0,
            sentiment="BULLISH",
            conviction_score=0.98,
            matched_keywords=["trump", "eth"],
        )

        result = await bot.on_catalyst_trigger(signal)
        assert result["success"] is True

        # Assert maker quotes were immediately cancelled in 0ms
        assert len(bot.execution.oms.active_orders) == 0
        assert bot.engine_state == "CATALYST_SNIPING"
        assert bot.active_catalyst is not None
        bot.execution.execute_taker_snipe.assert_awaited()

        # 3. Quoting cycle during cooldown: Maker quotes remain paused
        await bot._process_quoting_cycle(book)
        assert len(bot.execution.oms.active_orders) == 0

        # 4. Fast-forward past catalyst cooldown -> Quoting automatically resumes
        bot.risk_manager.record_heartbeat()
        bot.last_catalyst_time = time.time() - 10.0  # 10s ago > 5s cooldown
        await bot._process_quoting_cycle(book)
        assert bot.engine_state == "MAKER_QUOTING"
        assert len(bot.execution.oms.active_orders) > 0  # 0-fee AS quotes placed again!

    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_catalyst_gate_reject_cancels_quotes_without_snipe(monkeypatch):
    from lighter_mm_bot import LighterMarketMakerBot
    from lighter_news_sniper import CatalystSignal

    monkeypatch.setenv("ADMIN_CHAT_ID", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.delenv("NEWS_KILL_SWITCH", raising=False)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        bot = LighterMarketMakerBot(
            market_index=0,
            base_size=0.1,
            db_path=db_path,
            enable_telegram=False,
            enable_hybrid=True,
            catalyst_cooldown_sec=5.0,
        )
        bot._reconcile_every_n_cycles = 10_000
        await _wire_mm_execution_mocks(bot)
        bot._fetch_mm_collateral_usd = AsyncMock(return_value=None)

        book = make_test_book(mid=3000.0, spread=1.0)
        bot.current_book = book
        bot._record_book_update(book)
        await bot._process_quoting_cycle(book)
        assert len(bot.execution.oms.active_orders) > 0

        signal = CatalystSignal(
            news_id="test_cat_reject",
            headline="Donald Trump announces national strategic ETH reserve",
            target_asset="ETH",
            market_index=0,
            sentiment="BULLISH",
            conviction_score=0.98,
            matched_keywords=["trump", "eth"],
        )
        result = await bot.on_catalyst_trigger(signal)
        assert result["success"] is False
        assert result.get("error") == "risk_gate"
        assert len(bot.execution.oms.active_orders) == 0
        assert bot.engine_state == "CATALYST_SNIPING"
        bot.execution.execute_taker_snipe.assert_not_awaited()
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_stale_book_veto_cancels_and_skips_quotes(monkeypatch):
    from lighter_mm_bot import LighterMarketMakerBot

    monkeypatch.delenv("NEWS_KILL_SWITCH", raising=False)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        bot = LighterMarketMakerBot(
            market_index=0,
            base_size=0.1,
            db_path=db_path,
            enable_telegram=False,
            enable_hybrid=False,
        )
        bot._reconcile_every_n_cycles = 10_000
        bot._max_book_age_ms = 2000.0
        await _wire_mm_execution_mocks(bot)

        book = make_test_book(mid=3000.0, spread=1.0)
        book.timestamp = time.time()
        bot.current_book = book
        bot._record_book_update(book)
        await bot._process_quoting_cycle(book)
        assert len(bot.execution.oms.active_orders) > 0

        stale_ts = time.time() - 5.0
        book.timestamp = stale_ts
        bot._book_last_update_ts[0] = stale_ts
        bot.ws_streamer.last_update_ts = stale_ts
        bot._stale_book_latched = False

        await bot._process_quoting_cycle(book)
        assert len(bot.execution.oms.active_orders) == 0
        assert bot._stale_book_latched is True
    finally:
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass

