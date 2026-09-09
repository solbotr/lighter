#!/usr/bin/env python3
"""
Lighter DEX High-Frequency Market Maker (MM) Orchestrator
=========================================================
Master Entrypoint for Lighter DEX Market Making Bot:
- Real-time WebSocket Orderbook & Trades consumer
- Continuous Avellaneda-Stoikov & GLFT Quoting Engine
- Queue-preserving Deadband Order Management System (OMS)
- Institutional Risk Controls & Circuit Breakers
- SQLite Volume & Campaign Points Persistence
- Live Terminal Dashboard & Interactive Telegram Panel
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from lighter_db import LighterDBManager
from lighter_execution import (
    ActiveOrder,
    LighterExecutionEngine,
    LighterWebSocketStreamer,
)
from lighter_risk_manager import LighterRiskManager, RiskLimits
from lighter_strategy import (
    AvellanedaStoikovQuoter,
    L2OrderBook,
    OrderSide,
    TargetQuote,
)
from lighter_telegram import LighterTelegramBot, tg_send
from lighter_news_sniper import (
    CatalystClassifier,
    CatalystSignal,
    NewsIngestionManager,
    NewsItem,
)
from lighter_news_risk import LighterNewsRiskGate, MarketSnapshot
from news_pipeline import NormalizedNewsEvent
from anti_toxic_guard import AntiToxicMMGuard, AntiToxicGuardConfig

load_dotenv()

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("LighterMM")


def mask_sensitive(val: str, show_last: int = 4) -> str:
    """Masks secret keys in terminal output."""
    if not val or len(val) < 8:
        return "***"
    return val[:4] + "..." + val[-show_last:]


class LighterMarketMakerBot:
    """
    Master Market Maker Bot for zkLighter Orderbook DEX.
    Features Hybrid Quoting Engine:
    - In quiet market periods: 0-fee Avellaneda-Stoikov quoting to capture spread & farm Robinhood points.
    - Instant Catalyst Switch: Instantly cancels maker quotes and triggers directional taker snipe upon breaking news.
    """

    def __init__(
        self,
        market_index: int = 0,
        base_size: float = 0.05,
        target_spread_bps: float = 2.0,
        num_layers: int = 3,
        gamma: float = 0.05,
        kappa: float = 1.8,
        phi: float = 0.01,
        max_inventory: float = 1.0,
        soft_inventory: float = 0.5,
        max_daily_loss_usd: float = 100.0,
        db_path: str = "lighter_mm.db",
        enable_telegram: bool = True,
        enable_hybrid: bool = True,
        catalyst_cooldown_sec: float = 30.0,
    ):
        self.market_index = market_index
        self.base_size = base_size
        self.target_spread_bps = target_spread_bps
        self.num_layers = num_layers
        self.is_running = False
        self.enable_hybrid = enable_hybrid
        self.catalyst_cooldown_sec = catalyst_cooldown_sec
        self.engine_state = "MAKER_QUOTING"
        self.last_catalyst_time: float = 0.0
        self.active_catalyst: Optional[CatalystSignal] = None
        self._catalyst_exit: Optional[Dict[str, Any]] = None

        # 1. Initialize SQLite Database
        self.db = LighterDBManager(db_path=db_path)

        # 2. Initialize Quantitative Quoter (0-fee Avellaneda-Stoikov)
        self.quoter = AvellanedaStoikovQuoter(
            gamma=gamma,
            kappa=kappa,
            volatility=0.015,
            phi=phi,
            num_layers=num_layers,
            base_size=base_size,
            target_spread_bps=target_spread_bps,
        )

        # 3. Initialize Risk Manager
        limits = RiskLimits(
            max_inventory=max_inventory,
            soft_inventory_limit=soft_inventory,
            max_daily_loss_usd=max_daily_loss_usd,
        )
        self.risk_manager = LighterRiskManager(limits=limits)

        # 4. Initialize Execution Engine
        account_idx = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
        api_key_idx = int(os.getenv("LIGHTER_API_KEY_INDEX", "2"))
        private_key = os.getenv("LIGHTER_API_PRIVATE_KEY", "")
        base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai")

        self.execution = LighterExecutionEngine(
            base_url=base_url,
            account_index=account_idx,
            api_key_index=api_key_idx,
            api_private_key=private_key,
            market_index=market_index,
            on_fill_callback=self.on_fill_executed,
        )
        # Durable client_order_ids via same SQLite as fills
        self.execution.bind_cloid_store(self.db)

        # 5. Initialize WebSocket Streamer
        ws_url = os.getenv("LIGHTER_WS_URL", "wss://mainnet.zklighter.elliot.ai/stream")
        self.ws_streamer = LighterWebSocketStreamer(
            ws_url=ws_url,
            market_index=market_index,
            on_orderbook_callback=self.on_orderbook_update,
            on_heartbeat_callback=self.risk_manager.record_heartbeat,
        )

        # 6. Initialize Hybrid Catalyst Ingestion Streams
        self.classifier: Optional[CatalystClassifier] = None
        self.news_manager: Optional[NewsIngestionManager] = None
        if self.enable_hybrid:
            self.classifier = CatalystClassifier()
            news_db = os.getenv("NEWS_DB_PATH", db_path)
            self.news_manager = NewsIngestionManager(self._handle_news_event, db_path=news_db)

        # State tracking
        self.current_book: Optional[L2OrderBook] = None
        self.prev_book: Optional[L2OrderBook] = None
        self.last_dashboard_render: float = 0.0
        self.dashboard_interval_sec: float = 3.0
        self.loop = None
        self._quote_cycle_count = 0
        self._reconcile_every_n_cycles = int(os.getenv("MM_RECONCILE_EVERY_N", "50"))
        self._reconcile_task: Optional[asyncio.Task] = None
        self._reconcile_inflight = False
        self._quote_asset = os.getenv("LIGHTER_MM_ASSET", "ETH").upper()
        self._max_book_age_ms = float(os.getenv("MM_MAX_BOOK_AGE_MS", "2000"))
        self._book_last_update_ts: Dict[int, float] = {}
        self._stale_book_latched = False
        self._stale_watch_task: Optional[asyncio.Task] = None
        self._mm_started_at: float = 0.0
        self.news_risk_gate = LighterNewsRiskGate(live=True)

        # Anti-toxic lead-cancel: cancel maker quotes on velocity spikes
        self.anti_toxic_guard = AntiToxicMMGuard(
            config=AntiToxicGuardConfig(velocity_threshold_pct=0.0020),
            cancel_callback=self._anti_toxic_cancel_async,
        )

        # 7. Initialize Telegram Bot Context
        self.tg_bot = None
        if enable_telegram:
            self.tg_context = {
                "market_index": self.market_index,
                "quoter": self.quoter,
                "risk_manager": self.risk_manager,
                "execution_engine": self.execution,
                "db": self.db,
                "current_book": None,
                "bot_instance": self,
            }
            self.tg_bot = LighterTelegramBot(self.tg_context)

    async def _anti_toxic_cancel_async(self, asset=None) -> int:
        """Cancel-all callback for AntiToxicMMGuard toxic signals."""
        return await self.execution.cancel_all_orders()

    def _record_book_update(self, book: L2OrderBook, ts: Optional[float] = None) -> None:
        """Records last L2/depth update time for this market."""
        stamp = float(ts if ts is not None else (getattr(book, "timestamp", 0.0) or time.time()))
        self._book_last_update_ts[int(book.market_index)] = stamp
        ws = getattr(self, "ws_streamer", None)
        mark = getattr(ws, "mark_book_update", None) if ws is not None else None
        if callable(mark):
            mark(stamp)

    def _book_age_ms(self, book: Optional[L2OrderBook] = None, *, from_cycle: bool = False) -> float:
        """Milliseconds since the last real order_book/depth load. inf if never updated."""
        now = time.time()
        newest = 0.0
        mi = int(book.market_index) if book is not None else int(self.market_index)
        if from_cycle and book is not None:
            bts = float(getattr(book, "timestamp", 0.0) or 0.0)
            if bts > newest:
                newest = bts
        tracked = float(self._book_last_update_ts.get(mi, 0.0) or 0.0)
        if tracked > newest:
            newest = tracked
        ws = getattr(self, "ws_streamer", None)
        if ws is not None and int(getattr(ws, "market_index", mi)) == mi:
            wts = float(getattr(ws, "last_update_ts", 0.0) or 0.0)
            if wts > newest:
                newest = wts
        if newest <= 0:
            return float("inf")
        return max(0.0, (now - newest) * 1000.0)

    def _is_book_stale(self, book: Optional[L2OrderBook] = None, *, from_cycle: bool = False) -> bool:
        age_ms = self._book_age_ms(book, from_cycle=from_cycle)
        if age_ms == float("inf"):
            if self._mm_started_at <= 0:
                return False
            return (time.time() - self._mm_started_at) * 1000.0 > self._max_book_age_ms
        return age_ms > self._max_book_age_ms

    async def _enforce_stale_book_veto(
        self,
        book: Optional[L2OrderBook] = None,
        source: str = "watch",
    ) -> bool:
        """Cancel all quotes and skip this cycle when the book is older than MM_MAX_BOOK_AGE_MS."""
        from_cycle = source == "quote_cycle"
        if not self._is_book_stale(book, from_cycle=from_cycle):
            if self._stale_book_latched:
                age_ms = self._book_age_ms(book, from_cycle=from_cycle)
                logger.info(
                    "[MM STALE-BOOK] Book live again (age=%.0fms <= %.0fms). Quoting may resume.",
                    age_ms,
                    self._max_book_age_ms,
                )
                self._stale_book_latched = False
            return False

        age_ms = self._book_age_ms(book, from_cycle=from_cycle)
        age_label = "never" if age_ms == float("inf") else f"{age_ms:.0f}ms"
        try:
            canceled = await self.execution.cancel_all_orders()
        except Exception as e:
            logger.error("[MM STALE-BOOK] cancel_all_orders failed (%s): %s", source, e)
            canceled = -1
        if not self._stale_book_latched:
            logger.warning(
                "[MM STALE-BOOK] Veto: book age %s > MM_MAX_BOOK_AGE_MS=%.0f (%s). "
                "cancel_all_orders=%s, skipping new quotes.",
                age_label,
                self._max_book_age_ms,
                source,
                canceled,
            )
            self._stale_book_latched = True
        elif canceled not in (0, -1):
            logger.warning(
                "[MM STALE-BOOK] Still stale (age %s, %s). Pulled %s residual quote(s).",
                age_label,
                source,
                canceled,
            )
        return True

    async def _stale_book_watch_loop(self) -> None:
        interval = max(0.1, self._max_book_age_ms / 4000.0)
        while self.is_running:
            try:
                await asyncio.sleep(interval)
                if not self.is_running:
                    break
                await self._enforce_stale_book_veto(self.current_book, source="watch")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("[MM STALE-BOOK] Watch loop error: %s", e)

    async def _apply_money_safety_halt(self, book: Optional[L2OrderBook] = None) -> bool:
        """
        Kill/pause: cancel-all + optional flatten (once).
        Stale book / WS circuit: cancel-all, skip new quotes.
        Returns True when this cycle must not place quotes.
        """
        skip = False
        rm = self.risk_manager
        rm.check_kill_switch_file()
        news_kill = getattr(rm, "check_news_kill_switch", None)
        if callable(news_kill):
            news_kill()

        consume_halt = getattr(rm, "consume_halt_action", None)
        halt_reason = consume_halt() if callable(consume_halt) else None
        if halt_reason:
            halt_fn = getattr(self.execution, "emergency_halt", None)
            if callable(halt_fn):
                await halt_fn(reason=str(halt_reason), flatten=None)
            else:
                await self.execution.cancel_all_orders()
            skip = True
        elif rm.is_paused:
            skip = True

        if not rm.check_liveness():
            consume_stale = getattr(rm, "consume_stale_cancel", None)
            if callable(consume_stale) and consume_stale():
                await self.execution.cancel_all_orders()
            skip = True
        else:
            consume_stale = getattr(rm, "consume_stale_cancel", None)
            if callable(consume_stale) and consume_stale():
                await self.execution.cancel_all_orders()
                skip = True

        snap = book if book is not None else self.current_book
        if await self._enforce_stale_book_veto(snap, source="quote_cycle"):
            skip = True
        return skip

    def _book_to_snapshot(self, book: Optional[L2OrderBook], asset: str) -> Optional[MarketSnapshot]:
        if book is None or book.mid_price <= 0:
            return None
        ts = float(getattr(book, "timestamp", 0.0) or 0.0)
        tracked = float(self._book_last_update_ts.get(int(book.market_index), 0.0) or 0.0)
        if tracked > ts:
            ts = tracked
        return MarketSnapshot(
            asset=asset.upper(),
            price=float(book.mid_price),
            spread_bps=float(book.spread_bps),
            timestamp=ts if ts > 0 else time.time(),
            market_index=int(book.market_index),
        )

    def _mm_authorized(self) -> bool:
        chat_id = (os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        return bool(chat_id) and chat_id != "0"

    async def execute_strategy_entry(
        self,
        asset: str,
        market_index: int,
        is_ask: bool,
        price: float,
        *,
        notional_usd: Optional[float] = None,
        custom_tp_pct: Optional[float] = None,
        reason: str = "STRATEGY_ENTRY",
        entry_mode: str = "manual",
        stop_distance_pct: float = 1.5,
    ) -> Dict[str, Any]:
        """Telegram/manual opens on the MM process: risk gate → taker snipe (same caps as news)."""
        _ = custom_tp_pct  # MM taker path uses exchange defaults; retained for API parity with sniper
        symbol = (asset or "").upper()
        side = OrderSide.SELL if is_ask else OrderSide.BUY
        side_str = "SELL/SHORT" if is_ask else "BUY/LONG"
        if self.risk_manager.check_kill_switch_file() or self.risk_manager.is_paused:
            return {"success": False, "error": self.risk_manager.pause_reason or "MM kill/pause"}

        book = self.current_book
        if book is None or book.mid_price <= 0:
            return {"success": False, "error": "live book missing — cannot strategy-enter"}
        if int(market_index) not in (-1, self.market_index) and int(getattr(book, "market_index", self.market_index)) != int(market_index):
            # Allow alias markets that map to this MM market_index
            if int(market_index) != int(self.market_index):
                return {
                    "success": False,
                    "error": f"MM bot is on market {self.market_index}, not {market_index}",
                }

        snapshot = self._book_to_snapshot(book, symbol)
        if snapshot is None:
            return {"success": False, "error": "stale or empty snapshot"}
        snapshot.timestamp = time.time()
        exec_price = float(book.best_ask if side == OrderSide.BUY else book.best_bid) or float(book.mid_price) or float(price)
        cached_fn = getattr(self.execution, "cached_collateral_usd", None)
        collateral = cached_fn() if callable(cached_fn) else None
        if collateral is None or float(collateral) <= 0:
            collateral = await self._fetch_mm_collateral_usd()
        requested = float(notional_usd) if notional_usd is not None else float(
            os.getenv("NEWS_REQUESTED_USD", "100.0")
        )
        requested = min(self.news_risk_gate.max_trade_usd, requested)

        decision = await self.news_risk_gate.approve(
            None,
            snapshot,
            requested,
            confirmed=True,
            authorized=self._mm_authorized(),
            asset=symbol,
            side=side_str,
            collateral_usd=collateral,
            stop_distance_pct=stop_distance_pct,
            entry_mode=entry_mode,
        )
        if not decision.approved:
            return {
                "success": False,
                "error": "; ".join(decision.reasons) or "strategy gate rejected",
                "reasons": list(decision.reasons),
                "sized_usd": decision.sized_usd,
            }

        sized_usd = float(decision.sized_usd or requested)
        size = sized_usd / max(1e-9, exec_price)
        try:
            result = await self.execution.execute_taker_snipe(
                side=side,
                price=exec_price,
                size=size,
                reason=reason,
                orderbook=book,
            )
            if result.get("success"):
                self.news_risk_gate.record_fill(symbol)
                result.setdefault("entry_price", exec_price)
                result.setdefault("notional_usd", sized_usd)
                result.setdefault("asset", symbol)
            return result
        finally:
            if decision.reservation_id:
                await self.news_risk_gate.release(decision.reservation_id, symbol, side_str)

    def _event_for_catalyst(self, signal: CatalystSignal, event: Optional[Any]) -> Optional[Any]:
        if event is not None:
            return event
        now = datetime.now(timezone.utc)
        return NormalizedNewsEvent(
            event_id=signal.news_id,
            source_id="mm_catalyst",
            publisher="CatalystClassifier",
            headline=signal.headline,
            body=signal.headline,
            url="",
            guid=signal.news_id,
            published_at=now,
            ingested_at=now,
            source_score=float(signal.conviction_score),
            category="wire",
            content_hash=signal.news_id,
            entities=(str(signal.target_asset or self._quote_asset).upper(),),
            event_type="momentum",
            direction=signal.sentiment if signal.sentiment in {"BULLISH", "BEARISH"} else "NEUTRAL",
            confidence=float(signal.conviction_score),
            materiality=float(signal.conviction_score),
        )

    def _catalyst_confirmed(self, event: Optional[Any]) -> bool:
        if event is None:
            return False
        if self.news_manager is not None:
            try:
                if self.news_manager.pipeline.confirmed(event):
                    return True
            except Exception:
                pass
        from news_quality import quality_veto, require_two_sources

        ok, _reason = quality_veto(event)
        if not ok or getattr(event, "contradiction", False) or getattr(event, "invalidated", False):
            return False
        materiality = float(getattr(event, "materiality", 0.0) or 0.0)
        confidence = float(getattr(event, "confidence", 0.0) or 0.0)
        return bool(require_two_sources(event, 1, 1) and confidence >= 0.65 and materiality >= 0.40)

    async def _fetch_mm_collateral_usd(self) -> Optional[float]:
        exec_fn = getattr(self.execution, "fetch_available_collateral_usd", None)
        if callable(exec_fn):
            try:
                return await exec_fn()
            except Exception as e:
                logger.warning("[MM RISK] Collateral query failed: %s", e)
                return None
        account_index = int(getattr(self.execution, "account_index", 0) or 0)
        if account_index <= 0:
            logger.warning("[MM RISK] Collateral query failed: missing account index")
            return None
        try:
            session = await self.execution._get_http_session()
            url = f"{self.execution.base_url}/api/v1/account?by=index&value={account_index}"
            async with session.get(url) as resp:
                if resp.status != 200:
                    logger.warning("[MM RISK] Collateral query HTTP %s", resp.status)
                    return None
                data = await resp.json(content_type=None)
            accounts = data.get("accounts") or data.get("data") or ([data] if isinstance(data, dict) else [])
            for acc in accounts if isinstance(accounts, list) else [accounts]:
                if not isinstance(acc, dict):
                    continue
                for key in ("collateral", "available_balance", "available_collateral", "total_collateral", "balance"):
                    value = acc.get(key)
                    if value is None or value == "":
                        continue
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
        except Exception as e:
            logger.warning("[MM RISK] Collateral query failed: %s", e)
        return None

    async def _handle_news_event(self, news: NewsItem, event: Optional[Any] = None):
        """Processes incoming news headlines for instant catalyst classification."""
        if not self.enable_hybrid or not self.classifier:
            return

        signal = self.classifier.process_news(news)
        if signal:
            await self.on_catalyst_trigger(signal, event)

    async def on_catalyst_trigger(self, signal: CatalystSignal, event: Optional[Any] = None) -> Dict[str, Any]:
        """
        Instant Catalyst Switch:
        1. Immediately cancels all maker quotes (toxic pull).
        2. Switches engine state to CATALYST_SNIPING so quoting stays paused.
        3. News risk gate: notional, kill, confirmation, collateral, freshness.
        4. Fires directional taker snipe only if the gate approves.
        """
        logger.warning(
            f"⚡ [CATALYST SWITCH] Breaking Catalyst Detected: '{signal.headline}' | "
            f"Target: {signal.target_asset} | Sentiment: {signal.sentiment} (Score: {signal.conviction_score:.2f})"
        )

        self.engine_state = "CATALYST_SNIPING"
        self.last_catalyst_time = time.time()
        self.active_catalyst = signal

        canceled_count = await self.execution.cancel_all_orders()
        logger.info(f"⚡ [CATALYST SWITCH] Canceled {canceled_count} open maker quotes in 0ms.")

        side = OrderSide.BUY if signal.sentiment == "BULLISH" else OrderSide.SELL
        side_str = "BUY/LONG" if side == OrderSide.BUY else "SELL/SHORT"
        asset = (signal.target_asset or self._quote_asset).upper()
        snipe_size = self.base_size * 2.0

        exec_price = 0.0
        if self.current_book and self.current_book.mid_price > 0:
            exec_price = self.current_book.best_ask if side == OrderSide.BUY else self.current_book.best_bid
            if exec_price <= 0:
                exec_price = self.current_book.mid_price
        else:
            exec_price = float(os.getenv("LIGHTER_ETH_PRICE", "2650.0"))

        requested_usd = round(max(0.0, exec_price * snipe_size), 4)
        snapshot = self._book_to_snapshot(self.current_book, asset)
        news_event = self._event_for_catalyst(signal, event)
        confirmed = self._catalyst_confirmed(news_event)
        authorized = self._mm_authorized()
        collateral = await self._fetch_mm_collateral_usd()

        book_age_ms = self._book_age_ms(self.current_book, from_cycle=True)
        if self._is_book_stale(self.current_book, from_cycle=True):
            age_label = "never" if book_age_ms == float("inf") else f"{book_age_ms:.0f}ms"
            logger.warning(
                "[CATALYST] Snipe vetoed: stale book (age %s > MM_MAX_BOOK_AGE_MS=%.0f). Quotes already pulled.",
                age_label,
                self._max_book_age_ms,
            )
            return {
                "success": False,
                "error": "stale_book",
                "canceled": canceled_count,
                "book_age_ms": book_age_ms,
            }

        if self.risk_manager.check_kill_switch_file() or self.risk_manager.is_paused:
            logger.warning(
                "[CATALYST] Snipe vetoed: MM kill/pause (%s). Quotes already pulled.",
                self.risk_manager.pause_reason or "paused",
            )
            return {
                "success": False,
                "error": "kill_or_pause",
                "canceled": canceled_count,
            }

        decision = await self.news_risk_gate.approve(
            news_event,
            snapshot,
            requested_usd,
            confirmed,
            authorized,
            asset=asset,
            side=side_str,
            collateral_usd=collateral,
        )
        if not decision.approved:
            logger.warning(
                "[CATALYST] Snipe vetoed by news risk gate: %s (notional=$%.2f). Quotes already pulled.",
                "; ".join(decision.reasons),
                requested_usd,
            )
            tg_send(
                f"🚫 <b>HYBRID ENGINE: CATALYST SNIPE VETOED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"📰 <b>Headline:</b> {signal.headline}\n"
                f"🎯 <b>Asset:</b> {asset} (Market #{signal.market_index})\n"
                f"🚫 <b>Maker Quotes:</b> CANCELLED ({canceled_count} orders)\n"
                f"🛑 <b>Gate:</b> {'; '.join(decision.reasons)}\n"
                f"✨ <i>Quoting remains paused for catalyst cooldown. No taker snipe.</i>"
            )
            return {
                "success": False,
                "error": "risk_gate",
                "reasons": list(decision.reasons),
                "canceled": canceled_count,
            }

        sized_usd = float(decision.sized_usd or requested_usd)
        if exec_price > 0 and sized_usd > 0:
            snipe_size = sized_usd / exec_price

        try:
            result = await self.execution.execute_taker_snipe(
                side=side,
                price=exec_price,
                size=snipe_size,
                reason=f"CATALYST: {signal.headline[:40]}",
            )
            if result.get("success"):
                self.news_risk_gate.record_fill(asset)
                # ALWAYS arm TP/SL after catalyst entry (local + exchange reduce-only)
                asyncio.create_task(
                    self._arm_catalyst_tp_sl(
                        asset=asset,
                        side_str=side_str,
                        entry_price=float(result.get("vwap_price") or exec_price),
                        size=float(result.get("size") or snipe_size),
                        headline=signal.headline,
                    )
                )
        finally:
            if decision.reservation_id:
                await self.news_risk_gate.release(decision.reservation_id, asset, side_str)

        tg_text = (
            f"🚨 <b>HYBRID ENGINE: INSTANT CATALYST SWITCH</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📰 <b>Headline:</b> {signal.headline}\n"
            f"🎯 <b>Asset:</b> {signal.target_asset} (Market #{signal.market_index})\n"
            f"⚡ <b>Sentiment:</b> {signal.sentiment} (Score: {signal.conviction_score:.2f})\n"
            f"🚫 <b>Maker Quotes:</b> CANCELLED ({canceled_count} orders)\n"
            f"🚀 <b>Taker Snipe:</b> {side.value} {snipe_size:.4f} @ ${exec_price:,.2f}\n"
            f"💰 <b>Trade Notional:</b> ${exec_price * snipe_size:,.2f} USD\n"
            f"🛡️ <b>TP/SL:</b> arming after entry\n"
            f"✨ <i>0-fee Avellaneda-Stoikov quoting will safely resume after market stabilization.</i>"
        )
        tg_send(tg_text)

        return result

    async def _arm_catalyst_tp_sl(
        self,
        asset: str,
        side_str: str,
        entry_price: float,
        size: float,
        headline: str = "",
    ) -> None:
        """Attach reduce-only TP/SL after a hybrid catalyst fill."""
        from trade_exits import policy_for, tp_sl_prices, protect_limit_price

        try:
            await self.execution._ensure_signer()
        except Exception as e:
            logger.warning("[CATALYST TP/SL] signer unavailable: %s", e)
            return
        client = self.execution.signer_client
        if not client or entry_price <= 0 or size <= 0:
            return

        policy = policy_for(asset)
        tp_price, sl_price = tp_sl_prices(side_str, entry_price, policy)
        is_ask = side_str.startswith("BUY")
        price_decimals = int(getattr(self.execution, "price_decimals", 2) or 2)
        size_decimals = int(getattr(self.execution, "size_decimals", 4) or 4)
        if hasattr(self.execution, "scale_price_to_int"):
            tp_trig = self.execution.scale_price_to_int(tp_price)
            sl_trig = self.execution.scale_price_to_int(sl_price)
            tp_lim = self.execution.scale_price_to_int(protect_limit_price(side_str, "tp", tp_price))
            sl_lim = self.execution.scale_price_to_int(protect_limit_price(side_str, "sl", sl_price))
            size_int = self.execution.scale_size_to_int(size)
        else:
            tp_trig = int(round(tp_price * (10 ** price_decimals)))
            sl_trig = int(round(sl_price * (10 ** price_decimals)))
            tp_lim = int(round(protect_limit_price(side_str, "tp", tp_price) * (10 ** price_decimals)))
            sl_lim = int(round(protect_limit_price(side_str, "sl", sl_price) * (10 ** price_decimals)))
            size_int = int(round(size * (10 ** size_decimals)))
        if size_int <= 0:
            return

        tp_fn = getattr(client, "create_tp_order", None) or getattr(client, "create_tp_limit_order", None)
        sl_fn = getattr(client, "create_sl_order", None) or getattr(client, "create_sl_limit_order", None)
        tp_ok = sl_ok = False
        base_cid = int(time.time() * 1000) % 100_000_000
        try:
            if tp_fn:
                result = await tp_fn(
                    market_index=self.market_index,
                    client_order_index=base_cid,
                    base_amount=size_int,
                    trigger_price=tp_trig,
                    price=tp_lim if "limit" in getattr(tp_fn, "__name__", "") else tp_trig,
                    is_ask=is_ask,
                    reduce_only=True,
                )
                err = result[2] if isinstance(result, (tuple, list)) and len(result) >= 3 else None
                tp_ok = err is None
                if err:
                    logger.warning("[CATALYST TP] failed: %s", err)
            if sl_fn:
                result = await sl_fn(
                    market_index=self.market_index,
                    client_order_index=(base_cid + 7) % 100_000_000,
                    base_amount=size_int,
                    trigger_price=sl_trig,
                    price=sl_lim if "limit" in getattr(sl_fn, "__name__", "") else sl_trig,
                    is_ask=is_ask,
                    reduce_only=True,
                )
                err = result[2] if isinstance(result, (tuple, list)) and len(result) >= 3 else None
                sl_ok = err is None
                if err:
                    logger.warning("[CATALYST SL] failed: %s", err)
        except Exception as e:
            logger.warning("[CATALYST TP/SL] attach error: %s", e)

        # Track for local exit enforcement if exchange attach fails
        self._catalyst_exit = {
            "asset": asset,
            "side": side_str,
            "entry": entry_price,
            "size": size,
            "tp": tp_price,
            "sl": sl_price,
            "tp_ok": tp_ok,
            "sl_ok": sl_ok,
            "headline": headline[:80],
            "ts": time.time(),
        }
        logger.info(
            "🛡️ [CATALYST TP/SL] %s entry=$%.4f tp=$%.4f(%s) sl=$%.4f(%s)",
            asset, entry_price, tp_price, tp_ok, sl_price, sl_ok,
        )
        if not (tp_ok and sl_ok):
            tg_send(
                f"⚠️ <b>Catalyst TP/SL incomplete</b>\n"
                f"{asset} entry ${entry_price:,.4f}\n"
                f"TP ${tp_price:,.4f}={'OK' if tp_ok else 'FAIL'} | "
                f"SL ${sl_price:,.4f}={'OK' if sl_ok else 'FAIL'}\n"
                f"<i>Local flatten watchdog will enforce exits.</i>"
            )

    def on_fill_executed(
        self,
        order: ActiveOrder,
        fill_qty: float,
        fill_price: float,
        realized_pnl: float,
        is_maker: bool = True,
    ):
        """Callback invoked whenever a maker quote or taker snipe receives a fill."""
        usd_value = fill_qty * fill_price
        side_str = order.side.value

        # Update Risk Manager
        delta_inv = fill_qty if order.side == OrderSide.BUY else -fill_qty
        self.risk_manager.update_inventory(delta_inv)
        self.risk_manager.update_pnl(realized_pnl, usd_value)

        # Record to SQLite DB
        self.db.record_fill(
            market_index=self.market_index,
            order_id=order.order_id,
            client_order_id=str(order.client_order_id),
            side=side_str,
            price=fill_price,
            size=fill_qty,
            usd_value=usd_value,
            realized_pnl=realized_pnl,
            is_maker=is_maker,
        )

        # Console log
        pnl_badge = f"[PnL: ${realized_pnl:+.2f}]" if realized_pnl != 0 else ""
        fill_type = "MAKER" if is_maker else "TAKER SNIPE"
        logger.info(
            f"⚡ [{fill_type} FILL] {side_str} {fill_qty:.4f} @ ${fill_price:,.2f} (${usd_value:,.2f}) | "
            f"Inv: {self.risk_manager.inventory:+.4f} {pnl_badge}"
        )

        # Outbound Telegram notification
        stats = self.db.get_stats(market_index=self.market_index)
        title_badge = "⚡ <b>Maker Fill Executed</b>" if is_maker else "🚀 <b>Taker Catalyst Snipe Executed</b>"
        layer_badge = f" | <b>Layer:</b> {order.layer}" if is_maker and order.layer >= 0 else ""
        tg_text = (
            f"{title_badge}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Side:</b> {side_str}{layer_badge}\n"
            f"<b>Price:</b> ${fill_price:,.2f}\n"
            f"<b>Size:</b> {fill_qty:.4f} (${usd_value:,.2f})\n"
            f"<b>Realized PnL:</b> ${realized_pnl:+.2f}\n"
            f"<b>Current Inventory:</b> {self.risk_manager.inventory:+.4f}\n"
            f"<b>Total Volume:</b> ${stats['total_volume_usd']:,.2f}\n"
            f"<b>Estimated Points:</b> ✨ {stats['estimated_points']:.3f} pts"
        )
        tg_send(tg_text)

    def on_orderbook_update(self, book: L2OrderBook):
        """Callback triggered upon each Level-2 orderbook delta/snapshot."""
        self.prev_book = self.current_book
        self.current_book = book
        self._record_book_update(book)
        if self.tg_bot and hasattr(self, "tg_context"):
            self.tg_context["current_book"] = book

        if not self.is_running or not self.loop:
            return

        # Schedule high-frequency quoting cycle
        asyncio.run_coroutine_threadsafe(self._process_quoting_cycle(book), self.loop)

    async def _process_quoting_cycle(self, book: L2OrderBook):
        """Core asynchronous market making cycle with Hybrid Quoting Engine."""
        if book.mid_price <= 0:
            return

        # Money-safety: kill / pause → cancel-all + optional flatten; stale → cancel-all
        if await self._apply_money_safety_halt(book):
            now = time.time()
            if now - self.last_dashboard_render >= self.dashboard_interval_sec:
                self.last_dashboard_render = now
                self.render_dashboard(book)
            return

        # Enforce catalyst TP/SL locally if exchange attach incomplete
        await self._enforce_catalyst_exit(book)

        # Anti-toxic velocity check: pull quotes on toxic mid spikes
        toxic_event = await self.anti_toxic_guard.on_hyperliquid_price_tick_async(
            self._quote_asset, book.mid_price
        )
        if toxic_event is not None or self.anti_toxic_guard.is_quoting_paused(self._quote_asset):
            if toxic_event is not None:
                logger.warning("[ANTI-TOXIC] Quotes canceled: %s", toxic_event)
            return

        # Periodic live inventory reconciliation (background — never block quote cycle)
        self._quote_cycle_count += 1
        if (
            self._reconcile_every_n_cycles > 0
            and self._quote_cycle_count % self._reconcile_every_n_cycles == 0
        ):
            self._schedule_reconcile_live_inventory()

        # 0. Hybrid Engine Check: In catalyst stabilization window, keep maker quoting paused
        if self.enable_hybrid and self.engine_state == "CATALYST_SNIPING":
            if time.time() - self.last_catalyst_time >= self.catalyst_cooldown_sec:
                logger.info("🟢 [HYBRID] Catalyst cooldown expired. Market calm — Resuming 0-fee Avellaneda-Stoikov quoting.")
                self.engine_state = "MAKER_QUOTING"
                self.active_catalyst = None
            else:
                now = time.time()
                if now - self.last_dashboard_render >= self.dashboard_interval_sec:
                    self.last_dashboard_render = now
                    self.render_dashboard(book)
                return

        # 1. Generate Target Quotes using Avellaneda-Stoikov & GLFT (0-fee maker quoting)
        target_quotes = self.quoter.generate_quotes(
            book=book,
            inventory_q=self.risk_manager.inventory,
            prev_book=self.prev_book,
        )

        # 2. Validate Quotes with Risk Engine
        validated_quotes = self.risk_manager.validate_quotes(
            target_quotes=target_quotes,
            mid_price=book.mid_price,
            current_volatility=self.quoter.sigma,
        )

        # Halt may have engaged during validate (kill file / daily loss / NEWS_KILL)
        if await self._apply_money_safety_halt(book):
            return

        # 3. Compute Queue-Preserving Deadband Order Diff
        cancels, placements = self.execution.oms.compute_diff(
            target_quotes=validated_quotes,
            tick_size=self.quoter.tick_size,
        )

        # 4. Execute Batch Submissions / Cancellations
        if cancels or placements:
            await self.execution.execute_diff(cancels, placements)

        # 5. Render Dashboard Periodically
        now = time.time()
        if now - self.last_dashboard_render >= self.dashboard_interval_sec:
            self.last_dashboard_render = now
            self.render_dashboard(book)

    async def _enforce_catalyst_exit(self, book: L2OrderBook) -> None:
        """If catalyst inventory hits TP/SL, flatten immediately (backup to exchange orders)."""
        cx = self._catalyst_exit
        if not cx or book is None or book.mid_price <= 0:
            return
        mark = float(book.mid_price)
        side = str(cx.get("side") or "")
        tp = float(cx.get("tp") or 0)
        sl = float(cx.get("sl") or 0)
        hit = None
        if side.startswith("BUY"):
            if tp > 0 and mark >= tp:
                hit = "TAKE_PROFIT"
            elif sl > 0 and mark <= sl:
                hit = "STOP_LOSS"
        elif side.startswith("SELL"):
            if tp > 0 and mark <= tp:
                hit = "TAKE_PROFIT"
            elif sl > 0 and mark >= sl:
                hit = "STOP_LOSS"
        if not hit:
            return
        logger.warning("[CATALYST EXIT] %s hit %s @ $%.4f — flattening", cx.get("asset"), hit, mark)
        try:
            await self.execution.cancel_all_orders()
            await self.execution.flatten_inventory(reason=f"CATALYST_{hit}")
        except Exception as e:
            logger.error("[CATALYST EXIT] flatten failed: %s", e)
            return
        self._catalyst_exit = None
        self.engine_state = "MAKER_QUOTING"
        tg_send(
            f"🛡️ <b>Catalyst {hit}</b>\n"
            f"{cx.get('asset')} @ ${mark:,.4f}\n"
            f"TP ${tp:,.4f} / SL ${sl:,.4f}\n"
            f"<i>Inventory flattened; quoting resumes.</i>"
        )

    def _schedule_reconcile_live_inventory(self) -> None:
        """Kick reconcile off the quote hot-path (overlapping runs are coalesced)."""
        if self._reconcile_inflight:
            return
        task = self._reconcile_task
        if task is not None and not task.done():
            return

        async def _run() -> None:
            self._reconcile_inflight = True
            try:
                await self._reconcile_live_inventory()
            finally:
                self._reconcile_inflight = False

        self._reconcile_task = asyncio.create_task(_run())

    async def _reconcile_live_inventory(self) -> None:
        """Sync risk inventory from exchange positions."""
        try:
            result = await self.execution.reconcile_positions_and_fills()
            inv = float(result.get("inventory") or 0.0)
            self.risk_manager.set_inventory(inv)
            logger.info("[RECONCILE] Risk inventory set to %+.6f from exchange", inv)
        except Exception as e:
            logger.warning("[RECONCILE] Failed: %s", e)

    def render_dashboard(self, book: L2OrderBook):
        """Renders live terminal analytics and market state."""
        stats = self.db.get_stats(market_index=self.market_index)
        risk = self.risk_manager.get_status()
        active_orders = list(self.execution.oms.active_orders.values())
        buy_orders = [o for o in active_orders if o.side == OrderSide.BUY]
        sell_orders = [o for o in active_orders if o.side == OrderSide.SELL]

        mode_badge = "⚡ LIVE TRADING"
        if risk["is_paused"]:
            state_badge = "⏸️ PAUSED"
        elif self.engine_state == "CATALYST_SNIPING":
            state_badge = "⚡ CATALYST TAKER SNIPING"
        else:
            state_badge = "🟢 0-FEE AS QUOTING"

        print("\n" + "═" * 78)
        print(f"  LIGHTER DEX HYBRID MARKET MAKER & CATALYST SNIPER  |  {mode_badge}  |  {state_badge}")
        print("═" * 78)
        print(
            f"  Market: Index {self.market_index}  |  Mid: ${book.mid_price:,.2f}  |  "
            f"Spread: {book.spread_bps:.2f} bps (${book.spread:.2f})  |  Vol: {self.quoter.sigma*100:.2f}%"
        )
        print(
            f"  Inventory: {risk['inventory']:+.4f} units (Soft: ±{risk['soft_inventory']} | Hard: ±{risk['max_inventory']})  |  "
            f"Active Orders: {len(active_orders)} (Bids: {len(buy_orders)} | Asks: {len(sell_orders)})"
        )
        print("─" * 78)
        print(
            f"  Total Volume: ${stats['total_volume_usd']:,.2f}  |  "
            f"Fills: {stats['total_fills']} (Buy: {stats['buy_fills']} | Sell: {stats['sell_fills']})"
        )
        print(
            f"  Realized PnL: ${stats['total_realized_pnl_usd']:+,.2f} (Win: {stats.get('win_rate_pct', 0.0)}%)  |  "
            f"Estimated Points: ✨ {stats['estimated_points']:,.3f} pts (Robinhood Campaign)"
        )
        print("─" * 78)

        # Print active quotes table
        print(f"  {'LAYER':<6} {'BID SIZE':<10} {'BID PRICE':<12} | {'ASK PRICE':<12} {'ASK SIZE':<10}")
        max_layers = max(len(buy_orders), len(sell_orders), 1)
        for i in range(max_layers):
            b = buy_orders[i] if i < len(buy_orders) else None
            a = sell_orders[i] if i < len(sell_orders) else None
            bid_str = f"{b.size:.4f}" if b else "-"
            bid_p_str = f"${b.price:,.2f}" if b else "-"
            ask_p_str = f"${a.price:,.2f}" if a else "-"
            ask_str = f"{a.size:.4f}" if a else "-"
            print(f"  {i:<6} {bid_str:<10} {bid_p_str:<12} | {ask_p_str:<12} {ask_str:<10}")

        print("═" * 78)

    async def start(self):
        """Starts the market maker execution loop and hybrid news stream."""
        self.is_running = True
        self.loop = asyncio.get_running_loop()

        print("=" * 78)
        print("  STARTING LIGHTER DEX HYBRID MARKET MAKER BOT")
        print("  Mode: LIVE - REAL FUNDS")
        print(f"  Market Index: {self.market_index}")
        print(f"  Base Size: {self.base_size} | Target Half-Spread: {self.target_spread_bps} bps | Layers: {self.num_layers}")
        print(f"  Hybrid Engine: {'ENABLED (AS Quoting + Instant Catalyst Snipe)' if self.enable_hybrid else 'DISABLED (Pure MM)'}")
        print("=" * 78)

        # Start Telegram interactive bot
        if self.tg_bot:
            self.tg_bot.start_polling_in_background()

        # Start Hybrid News Ingestion Scheduler if enabled
        if self.enable_hybrid and self.news_manager:
            await self.news_manager.start()
            logger.info("📡 [HYBRID] News Ingestion & Catalyst Classifier active in background.")

        await self._reconcile_live_inventory()
        self._mm_started_at = time.time()
        self._stale_watch_task = asyncio.create_task(self._stale_book_watch_loop())
        logger.info(
            "[MM STALE-BOOK] Watch armed (MM_MAX_BOOK_AGE_MS=%.0f).",
            self._max_book_age_ms,
        )

        # Send launch notification
        tg_send(
            f"🚀 <b>Lighter Hybrid MM Bot Started</b>\n"
            f"<b>Mode:</b> ⚡ LIVE\n"
            f"<b>Market:</b> Index {self.market_index}\n"
            f"<b>Base Size:</b> {self.base_size}\n"
            f"<b>Target Half-Spread:</b> {self.target_spread_bps} bps\n"
            f"<b>Layers:</b> {self.num_layers}\n"
            f"<b>Hybrid Engine:</b> {'🟢 ACTIVE' if self.enable_hybrid else '🔴 DISABLED'}"
        )

        # Run WebSocket streaming loop
        await self.ws_streamer.start()

    async def shutdown(self):
        """Performs clean shutdown and quote cancellation."""
        logger.info("[SHUTDOWN] Canceling all active quotes on Lighter...")
        self.is_running = False
        task = self._stale_watch_task
        self._stale_watch_task = None
        if task is not None:
            task.cancel()
        self.ws_streamer.stop()

        canceled = await self.execution.cancel_all_orders()
        logger.info(f"[SHUTDOWN] Cancelled {canceled} open orders.")

        stats = self.db.get_stats(market_index=self.market_index)
        print("\n" + "=" * 78)
        print("  FINAL SESSION SUMMARY REPORT")
        print("=" * 78)
        print(f"  Total Maker Volume:   ${stats['total_volume_usd']:,.2f}")
        print(f"  Total Fills:          {stats['total_fills']}")
        print(f"  Realized PnL:         ${stats['total_realized_pnl_usd']:+,.2f}")
        print(f"  Win Rate:             {stats.get('win_rate_pct', 0.0):.1f}%")
        print(f"  Estimated Points:     ✨ {stats['estimated_points']:,.3f} pts")
        print("=" * 78 + "\n")


def parse_args():
    parser = argparse.ArgumentParser(description="Lighter DEX High-Frequency Market Maker Bot")
    parser.add_argument("--live", action="store_true", default=True, help="LIVE trading on zkLighter")
    parser.add_argument("--market", type=int, default=int(os.getenv("MARKET_INDEX", "0")), help="Market index (default: 0)")
    parser.add_argument("--size", type=float, default=float(os.getenv("BASE_ORDER_SIZE", "0.05")), help="Base order size in units")
    parser.add_argument("--spread", type=float, default=float(os.getenv("TARGET_SPREAD_BPS", "2.0")), help="Target half spread in bps")
    parser.add_argument("--layers", type=int, default=int(os.getenv("NUM_LAYERS", "3")), help="Number of quoting grid tiers")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram bot integration")
    parser.add_argument("--no-hybrid", action="store_true", help="Disable Hybrid instant catalyst switch engine")
    return parser.parse_args()


def main():
    args = parse_args()

    bot = LighterMarketMakerBot(
        market_index=args.market,
        base_size=args.size,
        target_spread_bps=args.spread,
        num_layers=args.layers,
        enable_telegram=not args.no_telegram,
        enable_hybrid=not args.no_hybrid,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_sigint(sig, frame):
        logger.info("\n[INTERRUPT] Received Ctrl+C / SIGINT signal. Initiating graceful shutdown...")
        asyncio.run_coroutine_threadsafe(bot.shutdown(), loop)
        loop.stop()

    signal.signal(signal.SIGINT, handle_sigint)

    try:
        loop.run_until_complete(bot.start())
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        loop.run_until_complete(bot.shutdown())
        loop.close()


if __name__ == "__main__":
    main()
