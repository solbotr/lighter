#!/usr/bin/env python3
"""
Execution Engine & Order Management System (OMS) for Lighter DEX
================================================================
Handles:
- Queue-preserving Deadband order diffing
- WebSocket Level-2 Orderbook streaming (wss://mainnet.zklighter.elliot.ai/stream)
- Lighter Protocol SignerClient / TransactionApi integration (L2 Tx)
- Atomic batch order placement and cancellation
"""

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import aiohttp
from lighter_strategy import L2OrderBook, OrderBookLevel, OrderSide, TargetQuote
from depth_vwap_engine import (
    DepthVWAPEngine,
    MicrostructureDepthBook,
    calculate_vwap,
    liquidity_adjusted_size,
    global_depth_vwap_engine,
)

logger = logging.getLogger(__name__)

# Lighter client_order_index space (keep well below 1e8).
_CLOID_MODULUS = 100_000_000
_CLOID_MIN = 1


def kill_flatten_enabled(default_true: bool = True) -> bool:
    """KILL_FLATTEN env: default true for live money-safety."""
    raw = os.getenv("KILL_FLATTEN")
    if raw is None or raw.strip() == "":
        return default_true
    return raw.strip().lower() in ("1", "true", "yes", "on")


class ClientOrderIdAllocator:
    """
    Persistent monotonic client_order_index allocator.
    Stores last id in SQLite (via LighterDBManager connection or path) or JSON fallback.
    Same intent_key reuses the same cloid across retries until complete_intent().
    """

    def __init__(
        self,
        store_path: Optional[str] = None,
        db_manager: Optional[Any] = None,
    ):
        self._db = db_manager
        default_json = os.path.join(
            os.path.dirname(os.path.abspath(__file__)) or ".",
            "client_order_ids.json",
        )
        if store_path:
            self._store_path = store_path
        elif db_manager is not None and getattr(db_manager, "db_path", None):
            self._store_path = str(db_manager.db_path)
        else:
            env_db = os.getenv("LIGHTER_DB_PATH") or os.getenv("NEWS_DB_PATH")
            self._store_path = env_db or default_json
        self._json_path = (
            self._store_path
            if self._store_path.endswith(".json")
            else os.path.splitext(self._store_path)[0] + "_cloids.json"
        )
        self._lock_intents: Dict[str, int] = {}
        self._last: int = self._bootstrap_last()

    def _bootstrap_last(self) -> int:
        seed = int(time.time() * 1000) % (_CLOID_MODULUS // 10)
        seed = max(_CLOID_MIN, seed)
        try:
            loaded = self._load_last()
            if loaded is not None and loaded >= _CLOID_MIN:
                return int(loaded) % _CLOID_MODULUS
        except Exception as e:
            logger.warning("[CLOID] Failed loading durable counter (%s); seeding fresh", e)
        self._persist(seed, {})
        return seed

    def _sqlite_conn(self):
        if self._db is not None and hasattr(self._db, "get_connection"):
            return self._db.get_connection()
        if self._store_path.endswith(".db") or self._store_path.endswith(".sqlite"):
            import sqlite3

            conn = sqlite3.connect(self._store_path, timeout=15.0)
            conn.execute("PRAGMA journal_mode=WAL;")
            return conn
        return None

    def _ensure_table(self, conn) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS client_order_id_seq (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_cloid INTEGER NOT NULL,
                intents_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        row = conn.execute(
            "SELECT last_cloid, intents_json FROM client_order_id_seq WHERE id = 1"
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO client_order_id_seq (id, last_cloid, intents_json) VALUES (1, ?, '{}')",
                (max(_CLOID_MIN, self._last if hasattr(self, "_last") else _CLOID_MIN),),
            )
            conn.commit()

    def _load_last(self) -> Optional[int]:
        conn = self._sqlite_conn()
        if conn is not None:
            try:
                self._ensure_table(conn)
                row = conn.execute(
                    "SELECT last_cloid, intents_json FROM client_order_id_seq WHERE id = 1"
                ).fetchone()
                if row:
                    try:
                        intents = json.loads(row[1] or "{}")
                        if isinstance(intents, dict):
                            self._lock_intents = {
                                str(k): int(v) for k, v in intents.items() if v is not None
                            }
                    except Exception:
                        pass
                    return int(row[0])
            finally:
                conn.close()
            return None
        path = self._json_path
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        intents = data.get("intents") or {}
        if isinstance(intents, dict):
            self._lock_intents = {str(k): int(v) for k, v in intents.items() if v is not None}
        return int(data.get("last_cloid") or data.get("last") or 0) or None

    def _persist(self, last: int, intents: Optional[Dict[str, int]] = None) -> None:
        intents = intents if intents is not None else dict(self._lock_intents)
        conn = self._sqlite_conn()
        if conn is not None:
            try:
                self._ensure_table(conn)
                conn.execute(
                    """
                    INSERT INTO client_order_id_seq (id, last_cloid, intents_json)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        last_cloid = excluded.last_cloid,
                        intents_json = excluded.intents_json
                    """,
                    (int(last), json.dumps(intents)),
                )
                conn.commit()
            finally:
                conn.close()
            return
        path = self._json_path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"last_cloid": int(last), "intents": intents}, fh)
        os.replace(tmp, path)

    def allocate(self, intent_key: Optional[str] = None) -> int:
        """Next monotonic cloid; reuse reserved id when intent_key is set and already allocated."""
        if intent_key:
            existing = self._lock_intents.get(intent_key)
            if existing is not None:
                return int(existing)
        self._last = (int(self._last) + 1) % _CLOID_MODULUS
        if self._last < _CLOID_MIN:
            self._last = _CLOID_MIN
        if intent_key:
            self._lock_intents[intent_key] = self._last
        try:
            self._persist(self._last, self._lock_intents)
        except Exception as e:
            logger.error("[CLOID] Persist failed after allocate: %s", e)
        return self._last

    def complete_intent(self, intent_key: Optional[str]) -> None:
        """Drop intent reservation after terminal success/abandon (counter stays)."""
        if not intent_key:
            return
        if intent_key in self._lock_intents:
            self._lock_intents.pop(intent_key, None)
            try:
                self._persist(self._last, self._lock_intents)
            except Exception as e:
                logger.warning("[CLOID] Persist failed on complete_intent: %s", e)

    def bind_db(self, db_manager: Any) -> None:
        """Attach LighterDBManager (or compatible) for SQLite-backed sequence."""
        self._db = db_manager
        if getattr(db_manager, "db_path", None):
            self._store_path = str(db_manager.db_path)
        try:
            loaded = self._load_last()
            if loaded is not None and loaded > self._last:
                self._last = int(loaded) % _CLOID_MODULUS
        except Exception as e:
            logger.warning("[CLOID] Rebind load failed: %s", e)


@dataclass
class ActiveOrder:
    client_order_id: int
    order_id: str
    side: OrderSide
    price: float
    size: float
    layer: int
    timestamp: float
    is_simulated: bool = False
    # Exchange-assigned order index used by cancel_order (NOT client_order_id).
    order_index: Optional[int] = None


class DeadbandOMS:
    """
    Queue-preserving Order Management System.
    Applies price deadbands and size drift thresholds to prevent unnecessary
    order cancellation churn, maintaining FIFO queue priority at Top-of-Book.
    """

    def __init__(
        self,
        price_deadband_ticks: int = 1,
        size_drift_pct: float = 0.15,
        stale_order_max_age_sec: float = 180.0,
    ):
        self.price_deadband_ticks = price_deadband_ticks
        self.size_drift_pct = size_drift_pct
        self.stale_order_max_age_sec = stale_order_max_age_sec
        self.active_orders: Dict[int, ActiveOrder] = {}  # Key: client_order_id

    def compute_diff(
        self,
        target_quotes: Dict[OrderSide, List[TargetQuote]],
        tick_size: float,
    ) -> Tuple[List[int], List[TargetQuote]]:
        """
        Calculates required cancellations (client_order_ids) and new quotes to place.
        Preserves active orders that are within deadband tolerances.
        """
        cancels_to_execute: List[int] = []
        quotes_to_place: List[TargetQuote] = []

        now = time.time()
        active_list = list(self.active_orders.values())
        matched_client_ids: Set[int] = set()

        for side in [OrderSide.BUY, OrderSide.SELL]:
            targets = target_quotes.get(side, [])
            for target in targets:
                # Find matching active order on same side & layer
                found_match: Optional[ActiveOrder] = None
                for order in active_list:
                    if (
                        order.client_order_id not in matched_client_ids
                        and order.side == side
                        and order.layer == target.layer
                    ):
                        found_match = order
                        break

                if found_match:
                    matched_client_ids.add(found_match.client_order_id)
                    # Check deadband thresholds
                    price_diff_ticks = abs(found_match.price - target.price) / max(0.0001, tick_size)
                    size_diff_pct = abs(found_match.size - target.size) / max(0.0001, found_match.size)
                    age = now - found_match.timestamp

                    # Replace only if deadband breached or order is excessively stale
                    if (
                        price_diff_ticks >= self.price_deadband_ticks
                        or size_diff_pct >= self.size_drift_pct
                        or age >= self.stale_order_max_age_sec
                    ):
                        cancels_to_execute.append(found_match.client_order_id)
                        quotes_to_place.append(target)
                else:
                    # No active order for this layer -> place new
                    quotes_to_place.append(target)

        # Cancel any orphan or leftover active orders
        for order in active_list:
            if order.client_order_id not in matched_client_ids:
                cancels_to_execute.append(order.client_order_id)

        return cancels_to_execute, quotes_to_place

    def register_order(self, order: ActiveOrder):
        """Registers a successfully submitted order in active state."""
        self.active_orders[order.client_order_id] = order

    def remove_order(self, client_order_id: int):
        """Removes an order from active state upon cancel or full fill."""
        self.active_orders.pop(client_order_id, None)

    def clear_all(self):
        """Clears all active orders from memory."""
        self.active_orders.clear()


class LighterExecutionEngine:
    """
    Master Execution Engine for Lighter DEX (live trading only).
    """

    def __init__(
        self,
        base_url: str = "https://mainnet.zklighter.elliot.ai",
        account_index: int = 0,
        api_key_index: int = 2,
        api_private_key: str = "",
        market_index: int = 0,
        price_decimals: int = 2,
        size_decimals: int = 4,
        tick_size: float = 0.01,
        on_fill_callback: Optional[Callable] = None,
    ):
        self.base_url = (os.getenv("LIGHTER_BASE_URL") or base_url).rstrip("/")
        env_account = os.getenv("LIGHTER_ACCOUNT_INDEX")
        if account_index > 0:
            self.account_index = int(account_index)
        elif env_account:
            self.account_index = int(env_account)
        else:
            self.account_index = 0
        self.api_key_index = int(api_key_index if api_key_index != 2 else os.getenv("LIGHTER_API_KEY_INDEX", "5"))
        self.api_private_key = api_private_key or os.getenv("LIGHTER_API_PRIVATE_KEY", "")
        self.market_index = market_index
        self.price_decimals = price_decimals
        self.size_decimals = size_decimals
        self.tick_size = tick_size
        self.on_fill_callback = on_fill_callback

        self.oms = DeadbandOMS()
        self.depth_engine = global_depth_vwap_engine
        cloid_store = os.getenv("LIGHTER_CLOID_PATH") or os.getenv("LIGHTER_DB_PATH")
        self.cloid_allocator = ClientOrderIdAllocator(store_path=cloid_store)
        self.signer_client = None
        self.signer_failed = False
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._cached_positions: List[Dict[str, Any]] = []
        self._last_positions_fetch_ts: float = 0.0
        self._ws_task: Optional[asyncio.Task] = None

    def _ensure_account_ws(self) -> None:
        if self.account_index <= 0:
            return
        if self._ws_task is None or self._ws_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._ws_task = loop.create_task(self._account_ws_stream_loop())
            except RuntimeError:
                pass

    async def _account_ws_stream_loop(self) -> None:
        """Real-time zero-lag WebSocket stream for account collateral and positions."""
        ws_url = os.getenv("LIGHTER_WS_URL", "wss://mainnet.zklighter.elliot.ai/stream")
        backoff = 1.0
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(ws_url, heartbeat=20.0) as ws:
                        logger.info("⚡ [WS] Real-time zkLighter account stream connected for LighterExecution (Account #%s)", self.account_index)
                        backoff = 1.0
                        while True:
                            msg = await ws.receive()
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                mtype = data.get("type")
                                if mtype == "connected":
                                    sub = {"type": "subscribe", "channel": f"account_all/{self.account_index}"}
                                    await ws.send_str(json.dumps(sub))
                                elif mtype in ("subscribed/account_all", "update/account_all"):
                                    raw_pos = data.get("positions") or {}
                                    pos_items = list(raw_pos.values()) if isinstance(raw_pos, dict) else (raw_pos if isinstance(raw_pos, list) else [])
                                    active_list = []
                                    for item in pos_items:
                                        parsed = self._parse_account_position(item)
                                        if parsed and float(parsed.get("size") or 0.0) > 0:
                                            active_list.append(parsed)
                                    self._cached_positions = active_list
                                    self._last_positions_fetch_ts = time.time()
                                elif mtype == "ping":
                                    await ws.send_str(json.dumps({"type": "pong"}))
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                                break
            except Exception as e:
                logger.debug("[WS Execution Account Stream Reconnect]: %s", e)
            await asyncio.sleep(backoff)
            backoff = min(10.0, backoff * 1.5)

    async def _get_http_session(self) -> aiohttp.ClientSession:
        if self._http_session is None or self._http_session.closed:
            speed = os.getenv("SPEED_MODE", "1").strip().lower() in {"1", "true", "yes", "on"}
            connector = aiohttp.TCPConnector(
                limit=80,
                limit_per_host=40,
                enable_cleanup_closed=True,
                keepalive_timeout=75.0,
                ttl_dns_cache=300,
                happy_eyeballs_delay=0.05,
            )
            total = 3.0 if speed else 8.0
            connect = 1.0 if speed else 3.0
            sock_read = 2.0 if speed else 5.0
            self._http_session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=total, connect=connect, sock_read=sock_read),
            )
        return self._http_session

    async def _ensure_signer(self) -> None:
        """Lazily initializes SignerClient within the active asyncio event loop."""
        if self.signer_client is not None:
            return
        if self.signer_failed:
            raise RuntimeError("Lighter signer previously failed; refusing live orders")
        if not self.api_private_key:
            self.signer_failed = True
            logger.critical("[EXEC] Live mode missing API private key — refusing orders (fail closed)")
            raise RuntimeError("LIGHTER_API_PRIVATE_KEY required in live mode")
        if self.account_index <= 0:
            self.signer_failed = True
            logger.critical("[EXEC] Live mode missing LIGHTER_ACCOUNT_INDEX — refusing orders (fail closed)")
            raise RuntimeError("LIGHTER_ACCOUNT_INDEX required in live mode")
        try:
            import lighter
            self.signer_client = lighter.SignerClient(
                url=self.base_url,
                api_private_keys={self.api_key_index: self.api_private_key},
                account_index=self.account_index,
            )
            logger.info(f"[EXEC] Lighter SignerClient initialized for account {self.account_index}")
        except Exception as e:
            self.signer_failed = True
            self.signer_client = None
            logger.critical(
                f"[EXEC] Failed to initialize lighter-sdk SignerClient: {e}. Failing closed."
            )
            raise

    @staticmethod
    def _coerce_int(value: Any) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _extract_order_index(self, *objs: Any) -> Optional[int]:
        """Best-effort parse of exchange order_index from create/cancel response objects."""
        keys = (
            "order_index",
            "OrderIndex",
            "orderIndex",
            "exchange_order_index",
            "index",
        )
        for obj in objs:
            if obj is None:
                continue
            if isinstance(obj, dict):
                for key in keys:
                    idx = self._coerce_int(obj.get(key))
                    if idx is not None and idx > 0:
                        return idx
                extras = obj.get("additional_properties")
                if isinstance(extras, dict):
                    for key in keys:
                        idx = self._coerce_int(extras.get(key))
                        if idx is not None and idx > 0:
                            return idx
                continue
            for key in keys:
                idx = self._coerce_int(getattr(obj, key, None))
                if idx is not None and idx > 0:
                    return idx
            extras = getattr(obj, "additional_properties", None)
            if isinstance(extras, dict):
                for key in keys:
                    idx = self._coerce_int(extras.get(key))
                    if idx is not None and idx > 0:
                        return idx
        return None

    def _parse_account_position(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Lighter sends abs `position` plus `sign` (1 long / -1 short)."""
        if not isinstance(item, dict):
            return None
        try:
            size = float(item.get("position") or item.get("size") or item.get("base_amount") or 0)
        except (TypeError, ValueError):
            return None
        if abs(size) <= 0:
            return None
        sign_raw = item.get("sign")
        try:
            sign = int(sign_raw) if sign_raw is not None and sign_raw != "" else (1 if size > 0 else -1)
        except (TypeError, ValueError):
            sign = 1 if size > 0 else -1
        raw_mid = item.get("market_id")
        if raw_mid is None:
            raw_mid = item.get("market_index")
        try:
            market_id = int(raw_mid) if raw_mid is not None and raw_mid != "" else -1
        except (TypeError, ValueError):
            market_id = -1
        symbol = str(item.get("symbol") or item.get("market_symbol") or "").upper()
        try:
            entry = float(item.get("avg_entry_price") or item.get("entry_price") or item.get("avg_price") or 0)
        except (TypeError, ValueError):
            entry = 0.0
        return {
            "symbol": symbol,
            "market_index": market_id,
            "size": abs(size),
            "signed": abs(size) * (1 if sign >= 0 else -1),
            "side": "BUY/LONG" if sign >= 0 else "SELL/SHORT",
            "entry_price": entry,
        }

    async def fetch_account_positions(self) -> List[Dict[str, Any]]:
        """Fetches live account positions from Lighter WebSocket stream or REST."""
        self._ensure_account_ws()
        now = time.time()
        if self._last_positions_fetch_ts > 0 and (now - self._last_positions_fetch_ts) < 15.0:
            return self._cached_positions
        if self.account_index <= 0:
            return self._cached_positions
        if self._cached_positions:
            return self._cached_positions
        try:
            session = await self._get_http_session()
            url = f"{self.base_url}/api/v1/account?by=index&value={self.account_index}&active_only=true"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    accounts = data.get("accounts") or data.get("data") or ([data] if isinstance(data, dict) else [])
                    positions: List[Dict[str, Any]] = []
                    for acc in accounts if isinstance(accounts, list) else [accounts]:
                        if not isinstance(acc, dict):
                            continue
                        raw = acc.get("positions") or acc.get("position") or []
                        if isinstance(raw, dict):
                            raw = list(raw.values())
                        for item in raw:
                            parsed = self._parse_account_position(item)
                            if parsed:
                                positions.append(parsed)
                    self._cached_positions = positions
                    self._last_positions_fetch_ts = now
                    return positions
        except Exception as e:
            logger.warning("[EXEC] Account position fetch failed: %s", e)
        return self._cached_positions

    async def fetch_open_orders(self) -> List[Dict[str, Any]]:
        """Fetches open orders so we can resolve exchange order_index by client id."""
        if self.account_index <= 0:
            return []
        orders: List[Dict[str, Any]] = []
        urls = [
            f"{self.base_url}/api/v1/account?by=index&value={self.account_index}",
            f"{self.base_url}/api/v1/accountActiveOrders?account_index={self.account_index}",
        ]
        try:
            session = await self._get_http_session()
            for url in urls:
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.json(content_type=None)
                        orders.extend(self._extract_orders_from_payload(data))
                except Exception:
                    continue
        except Exception as e:
            logger.debug("[EXEC] fetch_open_orders error: %s", e)
        return orders

    def _extract_orders_from_payload(self, data: Any) -> List[Dict[str, Any]]:
        orders: List[Dict[str, Any]] = []
        if not isinstance(data, dict):
            return orders
        candidates: List[Any] = []
        for key in ("orders", "active_orders", "account_orders", "data", "accounts"):
            raw = data.get(key)
            if isinstance(raw, list):
                candidates.extend(raw)
            elif isinstance(raw, dict):
                candidates.extend(raw.values())
        if not candidates and (
            data.get("order_index") is not None or data.get("client_order_index") is not None
        ):
            candidates.append(data)
        for item in candidates:
            if isinstance(item, dict):
                if item.get("orders") or item.get("active_orders"):
                    orders.extend(self._extract_orders_from_payload(item))
                elif (
                    item.get("order_index") is not None
                    or item.get("client_order_index") is not None
                    or item.get("price") is not None
                ):
                    orders.append(item)
        return orders

    async def resolve_exchange_order_index(self, client_order_id: int) -> Optional[int]:
        """Looks up exchange order_index for a client_order_id via account open orders."""
        try:
            for item in await self.fetch_open_orders():
                client_idx = self._coerce_int(
                    item.get("client_order_index") or item.get("client_order_id")
                )
                if client_idx == client_order_id:
                    idx = self._coerce_int(
                        item.get("order_index") or item.get("order_id") or item.get("index")
                    )
                    if idx is not None and idx > 0:
                        return idx
        except Exception as e:
            logger.warning(
                "[EXEC] Failed resolving order_index for client_order_id=%s: %s",
                client_order_id,
                e,
            )
        return None

    async def reconcile_positions_and_fills(self) -> Dict[str, Any]:
        """
        Live inventory reconciliation against Lighter account positions.
        Returns signed inventory for this market_index.
        """
        positions = await self.fetch_account_positions()
        signed = 0.0
        entry = 0.0
        matched: Optional[Dict[str, Any]] = None
        for item in positions:
            if int(item.get("market_index", -1)) == int(self.market_index):
                matched = item
                signed = float(item.get("signed") or 0.0)
                entry = float(item.get("entry_price") or 0.0)
                break
        logger.info(
            "[EXEC] Reconcile market=%s inventory=%+.6f entry=%.4f (positions=%s)",
            self.market_index,
            signed,
            entry,
            len(positions),
        )
        return {
            "skipped": False,
            "inventory": signed,
            "entry_price": entry,
            "position": matched,
            "positions": positions,
        }

    async def _exchange_cancel_all(self) -> bool:
        """Calls signer cancel_all_orders for this market when available."""
        if self.signer_client is None or not hasattr(self.signer_client, "cancel_all_orders"):
            return False
        try:
            tif = getattr(self.signer_client, "CANCEL_ALL_TIF_IMMEDIATE", 0)
            tx, tx_hash, err = await self.signer_client.cancel_all_orders(
                time_in_force=tif,
                timestamp_ms=0,
                cancel_all_market_index=int(self.market_index),
                api_key_index=self.api_key_index,
            )
            if err:
                logger.error("[EXEC] Exchange cancel_all_orders failed: %s", err)
                return False
            logger.warning(
                "[EXEC] Exchange cancel_all_orders submitted for market %s (tx=%s)",
                self.market_index,
                tx_hash,
            )
            return True
        except Exception as e:
            logger.error("[EXEC] Exchange cancel_all_orders exception: %s", e)
            return False

    def bind_cloid_store(self, db_manager: Any) -> None:
        """Prefer LighterDBManager SQLite for durable client_order_id sequence."""
        self.cloid_allocator.bind_db(db_manager)

    def get_next_client_order_id(self, intent_key: Optional[str] = None) -> int:
        """Durable monotonic client_order_index; same intent_key reuses on retry."""
        return self.cloid_allocator.allocate(intent_key)

    def complete_client_order_intent(self, intent_key: Optional[str]) -> None:
        self.cloid_allocator.complete_intent(intent_key)

    def scale_price_to_int(self, price: float) -> int:
        """Scales float price to Lighter integer representation."""
        return int(round(price * (10 ** self.price_decimals)))

    def scale_size_to_int(self, size: float) -> int:
        """Scales float size to Lighter integer representation."""
        return int(round(size * (10 ** self.size_decimals)))

    async def execute_diff(
        self,
        cancels: List[int],
        placements: List[TargetQuote],
    ) -> Tuple[int, int]:
        """
        Executes order cancellations and new quote placements.
        Returns: (cancels_count, placements_count)
        """
        if self.signer_failed:
            logger.critical("[EXEC] execute_diff refused — signer_failed")
            return 0, 0

        canceled_count = 0
        placed_count = 0

        # 1. Execute Cancellations
        if cancels:
            for client_id in cancels:
                success = await self._cancel_order(client_id)
                if success:
                    self.oms.remove_order(client_id)
                    canceled_count += 1

        # 2. Execute Placements
        if placements:
            for quote in placements:
                intent = (
                    f"mm:{self.market_index}:{quote.side.value}:L{quote.layer}:"
                    f"{quote.price:.8f}:{quote.size:.8f}"
                )
                client_id = self.get_next_client_order_id(intent_key=intent)
                order_id, order_index = await self._place_order(client_id, quote)
                if order_id:
                    self.complete_client_order_intent(intent)
                    if order_index is None:
                        order_index = await self.resolve_exchange_order_index(client_id)
                        if order_index is None:
                            logger.error(
                                "[EXEC] Placed order client_id=%s but exchange order_index unknown — "
                                "cancel will require cancel-all fallback",
                                client_id,
                            )
                    self.oms.register_order(
                        ActiveOrder(
                            client_order_id=client_id,
                            order_id=order_id,
                            side=quote.side,
                            price=quote.price,
                            size=quote.size,
                            layer=quote.layer,
                            timestamp=time.time(),
                            order_index=order_index,
                        )
                    )
                    placed_count += 1

        return canceled_count, placed_count

    async def _place_order(
        self, client_order_id: int, quote: TargetQuote
    ) -> Tuple[Optional[str], Optional[int]]:
        """Submits a single limit order. Returns (order_id, exchange order_index)."""
        if self.signer_failed:
            logger.critical("[EXEC] Place refused — signer_failed")
            return None, None

        try:
            await self._ensure_signer()
        except Exception:
            return None, None

        if self.signer_client:
            try:
                price_int = self.scale_price_to_int(quote.price)
                size_int = self.scale_size_to_int(quote.size)
                is_ask = (quote.side == OrderSide.SELL)

                # Order type: Limit Post-Only
                order_type = getattr(self.signer_client, "ORDER_TYPE_LIMIT", 0)
                time_in_force = getattr(self.signer_client, "ORDER_TIME_IN_FORCE_POST_ONLY", 2)

                tx, tx_hash, err = await self.signer_client.create_order(
                    market_index=self.market_index,
                    client_order_index=client_order_id,
                    base_amount=size_int,
                    price=price_int,
                    is_ask=is_ask,
                    order_type=order_type,
                    time_in_force=time_in_force,
                    api_key_index=self.api_key_index,
                )
                if err:
                    logger.warning(f"[EXEC] Order create rejected: {err}")
                    return None, None

                order_index = self._extract_order_index(tx, tx_hash)
                order_id = str(
                    getattr(tx_hash, "tx_hash", None)
                    or tx_hash
                    or client_order_id
                )
                return order_id, order_index
            except Exception as e:
                logger.error(f"[EXEC] Failed to create order {client_order_id}: {e}")
                return None, None

        return None, None

    async def _cancel_order(self, client_order_id: int) -> bool:
        """Cancels a single order using exchange order_index (never client_order_id)."""
        if self.signer_failed:
            logger.critical(
                "[EXEC] Cancel refused for client_order_id=%s — signer_failed",
                client_order_id,
            )
            return False

        order = self.oms.active_orders.get(client_order_id)
        order_index = order.order_index if order else None

        if order_index is None:
            order_index = await self.resolve_exchange_order_index(client_order_id)
            if order is not None and order_index is not None:
                order.order_index = order_index

        if order_index is None:
            logger.error(
                "[EXEC] Cannot cancel client_order_id=%s — exchange order_index missing. "
                "Attempting exchange cancel-all API (not pretending success).",
                client_order_id,
            )
            try:
                await self._ensure_signer()
            except Exception:
                return False
            return await self._exchange_cancel_all()

        try:
            await self._ensure_signer()
        except Exception:
            return False

        if self.signer_client:
            try:
                tx, tx_hash, err = await self.signer_client.cancel_order(
                    market_index=self.market_index,
                    order_index=int(order_index),
                    api_key_index=self.api_key_index,
                )
                if err:
                    logger.warning(
                        "[EXEC] Order cancel rejected for order_index=%s (client=%s): %s",
                        order_index,
                        client_order_id,
                        err,
                    )
                    return False
                return True
            except Exception as e:
                logger.error(
                    "[EXEC] Failed to cancel order_index=%s (client=%s): %s",
                    order_index,
                    client_order_id,
                    e,
                )
                return False

        logger.error("[EXEC] Cancel failed — signer client unavailable")
        return False

    async def cancel_all_orders(self) -> int:
        """Emergency cancellation of all active quotes via exchange order_index / cancel-all."""
        active_orders = list(self.oms.active_orders.values())
        count = len(active_orders)

        if self.signer_failed:
            logger.critical("[EXEC] cancel_all_orders refused — signer_failed")
            return 0

        try:
            await self._ensure_signer()
        except Exception:
            return 0

        canceled = 0
        missing_index: List[int] = []

        # Prefer exchange cancel-all for this market (authoritative wipe).
        api_ok = await self._exchange_cancel_all()

        if self.signer_client:
            for order in active_orders:
                if order.order_index is None:
                    resolved = await self.resolve_exchange_order_index(order.client_order_id)
                    if resolved is not None:
                        order.order_index = resolved
                if order.order_index is None:
                    missing_index.append(order.client_order_id)
                    continue
                try:
                    tx, tx_hash, err = await self.signer_client.cancel_order(
                        market_index=self.market_index,
                        order_index=int(order.order_index),
                        api_key_index=self.api_key_index,
                    )
                    if err:
                        logger.warning(
                            "[EXEC] cancel_all per-order failed order_index=%s: %s",
                            order.order_index,
                            err,
                        )
                    else:
                        canceled += 1
                except Exception as e:
                    logger.error(
                        "[EXEC] cancel_all per-order exception order_index=%s: %s",
                        order.order_index,
                        e,
                    )

        if missing_index:
            logger.error(
                "[EXEC] cancel_all_orders: %s order(s) missing exchange order_index "
                "(client_ids=%s). cancel-all API used=%s — not claiming silent success.",
                len(missing_index),
                missing_index,
                api_ok,
            )
            if not api_ok:
                # Last-chance cancel-all already attempted above; leave OMS uncleared for those.
                for cid in list(self.oms.active_orders.keys()):
                    if cid not in missing_index:
                        self.oms.remove_order(cid)
                return canceled

        if api_ok or canceled >= count or not missing_index:
            self.oms.clear_all()
            return count if api_ok else canceled

        return canceled

    async def flatten_inventory(self, reason: str = "KILL_FLATTEN") -> Dict[str, Any]:
        """
        Reduce-only close of this market's open position via taker.
        Returns status dict; success=True when flat or already flat.
        """
        out: Dict[str, Any] = {"success": False, "flattened": False, "reason": reason}
        if self.signer_failed:
            out["error"] = "signer_failed"
            logger.critical("[EXEC] Flatten refused — signer_failed")
            return out
        recon = await self.reconcile_positions_and_fills()
        signed = float(recon.get("inventory") or 0.0)
        if abs(signed) <= 1e-12:
            out["success"] = True
            out["flattened"] = True
            out["inventory"] = 0.0
            return out

        side = OrderSide.SELL if signed > 0 else OrderSide.BUY
        size = abs(signed)
        entry = float(recon.get("entry_price") or 0.0)
        price = entry if entry > 0 else float(os.getenv("LIGHTER_ETH_PRICE", "2650.0"))
        intent = f"flatten:{self.market_index}:{side.value}:{size:.8f}"
        client_id = self.get_next_client_order_id(intent_key=intent)

        try:
            await self._ensure_signer()
        except Exception as e:
            out["error"] = str(e)
            return out

        if not self.signer_client:
            out["error"] = "signer unavailable"
            return out

        try:
            price_int = self.scale_price_to_int(price * (1.01 if side == OrderSide.BUY else 0.99))
            size_int = self.scale_size_to_int(size)
            if size_int <= 0:
                out["error"] = "size rounds to 0"
                return out
            is_ask = side == OrderSide.SELL
            order_type = getattr(self.signer_client, "ORDER_TYPE_MARKET", 1)
            time_in_force = getattr(self.signer_client, "ORDER_TIME_IN_FORCE_IOC", 1)
            kwargs: Dict[str, Any] = {
                "market_index": self.market_index,
                "client_order_index": client_id,
                "base_amount": size_int,
                "price": price_int,
                "is_ask": is_ask,
                "order_type": order_type,
                "time_in_force": time_in_force,
                "api_key_index": self.api_key_index,
            }
            # Prefer reduce-only when SDK supports it.
            try:
                tx, tx_hash, err = await self.signer_client.create_order(**kwargs, reduce_only=True)
            except TypeError:
                tx, tx_hash, err = await self.signer_client.create_order(**kwargs)
            if err:
                logger.error("[EXEC] Flatten order rejected: %s", err)
                out["error"] = str(err)
                return out
            self.complete_client_order_intent(intent)
            logger.warning(
                "[EXEC] Flatten submitted market=%s side=%s size=%s reason=%s tx=%s",
                self.market_index,
                side.value,
                size,
                reason,
                tx_hash,
            )
            out["success"] = True
            out["flattened"] = True
            out["client_order_id"] = client_id
            out["inventory_before"] = signed
            out["side"] = side.value
            out["size"] = size
            return out
        except Exception as e:
            logger.error("[EXEC] Flatten exception: %s", e)
            out["error"] = str(e)
            return out

    async def emergency_halt(
        self,
        reason: str = "KILL",
        flatten: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Money-safety path: exchange cancel-all, then optional inventory flatten.
        flatten=None → KILL_FLATTEN env (default true).
        """
        do_flatten = kill_flatten_enabled(True) if flatten is None else bool(flatten)
        logger.critical(
            "[EXEC] emergency_halt reason=%s cancel_all + flatten=%s",
            reason,
            do_flatten,
        )
        canceled = await self.cancel_all_orders()
        flat_result: Dict[str, Any] = {"skipped": True}
        if do_flatten:
            flat_result = await self.flatten_inventory(reason=reason)
        return {
            "reason": reason,
            "canceled": canceled,
            "flatten_requested": do_flatten,
            "flatten": flat_result,
        }

    def calculate_vwap_and_size(
        self,
        side: OrderSide,
        target_notional_usd: float,
        max_slippage_bps: float = 50.0,
        orderbook: Optional[Any] = None,
        fallback_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Calculates VWAP and slippage-adjusted size for this market index."""
        book = orderbook or self.depth_engine.get_or_create_book(self.market_index)
        adj_usd = liquidity_adjusted_size(
            orderbook=book,
            side=side.value,
            requested_usd=target_notional_usd,
            max_slippage_bps=max_slippage_bps,
            fallback_price=fallback_price,
        )
        vwap_price, filled_usd, slippage_bps, depth_exhausted = calculate_vwap(
            orderbook=book,
            side=side.value,
            target_notional_usd=adj_usd,
            fallback_price=fallback_price,
        )
        return {
            "requested_usd": target_notional_usd,
            "executable_usd": adj_usd,
            "vwap_price": vwap_price,
            "filled_usd": filled_usd,
            "expected_slippage_bps": slippage_bps,
            "depth_exhausted": depth_exhausted,
        }

    async def execute_taker_snipe(
        self,
        side: OrderSide,
        price: float,
        size: float,
        reason: str = "CATALYST_SNIPE",
        orderbook: Optional[Any] = None,
        max_slippage_bps: float = 50.0,
    ) -> Dict[str, Any]:
        """
        Executes an immediate directional taker snipe order on the DEX.
        Used for instantaneous catalyst reactions when breaking news hits.
        Calculates VWAP and expected slippage across available orderbook depth.
        """
        intent = f"snipe:{self.market_index}:{side.value}:{price:.8f}:{size:.8f}:{reason}"
        client_id = self.get_next_client_order_id(intent_key=intent)
        usd_value = price * size
        is_ask = (side == OrderSide.SELL)

        # Microstructure VWAP calculation
        vwap_meta = self.calculate_vwap_and_size(
            side=side,
            target_notional_usd=usd_value,
            max_slippage_bps=max_slippage_bps,
            orderbook=orderbook,
            fallback_price=price,
        )
        vwap_price = vwap_meta.get("vwap_price") or price
        slippage_bps = vwap_meta.get("expected_slippage_bps", 0.0)

        # Enforce executable USD size and verify slippage cap
        exec_usd = vwap_meta.get("executable_usd", usd_value)
        if exec_usd <= 0 or slippage_bps > max_slippage_bps:
            logger.warning(f"[VWAP] Slippage cap exceeded ({slippage_bps:.1f} bps > {max_slippage_bps} bps)")
            return {"success": False, "error": f"Slippage cap exceeded ({slippage_bps:.1f} bps > {max_slippage_bps} bps)"}

        safe_size = size if orderbook is None else min(size, max(0.0, exec_usd / price))
        worst_price = vwap_price * (1.0 + (max_slippage_bps / 10000.0)) if side == OrderSide.BUY else vwap_price * (1.0 - (max_slippage_bps / 10000.0))
        exec_price = worst_price if worst_price > 0 else price

        if self.signer_failed:
            logger.critical("[EXEC] Taker snipe refused — signer_failed")
            return {"success": False, "error": "signer_failed"}

        try:
            await self._ensure_signer()
        except Exception as e:
            return {"success": False, "error": str(e)}

        if self.signer_client:
            try:
                price_int = self.scale_price_to_int(exec_price)
                size_int = self.scale_size_to_int(safe_size)
                order_type = getattr(self.signer_client, "ORDER_TYPE_MARKET", 1)
                time_in_force = getattr(self.signer_client, "ORDER_TIME_IN_FORCE_IOC", 1)

                tx, tx_hash, err = await self.signer_client.create_order(
                    market_index=self.market_index,
                    client_order_index=client_id,
                    base_amount=size_int,
                    price=price_int,
                    is_ask=is_ask,
                    order_type=order_type,
                    time_in_force=time_in_force,
                    api_key_index=self.api_key_index,
                )
                if err:
                    logger.error(f"[EXEC] Taker snipe rejected: {err}")
                    return {"success": False, "error": str(err)}

                self.complete_client_order_intent(intent)
                order_index = self._extract_order_index(tx, tx_hash)
                return {
                    "success": True,
                    "client_order_id": client_id,
                    "order_id": str(getattr(tx_hash, "tx_hash", None) or tx_hash or client_id),
                    "order_index": order_index,
                    "side": side.value,
                    "price": price,
                    "vwap_price": vwap_price,
                    "size": size,
                    "usd_value": usd_value,
                    "expected_slippage_bps": slippage_bps,
                    "depth_exhausted": vwap_meta.get("depth_exhausted", False),
                    "realized_pnl": 0.0,
                    "is_maker": False,
                    "mode": "LIVE",
                    "reason": reason,
                }
            except Exception as e:
                logger.error(f"[EXEC] Failed to execute taker snipe: {e}")
                return {"success": False, "error": str(e)}

        return {"success": False, "error": "Signer client not initialized"}


class LighterWebSocketStreamer:
    """
    WebSocket client streaming real-time Level 2 orderbook depth and trades
    from zkLighter (wss://mainnet.zklighter.elliot.ai/stream).
    Includes automatic keepalive ping frames every 60s.
    """

    def __init__(
        self,
        ws_url: str = "wss://mainnet.zklighter.elliot.ai/stream",
        market_index: int = 0,
        on_orderbook_callback: Optional[Callable[[L2OrderBook], None]] = None,
        on_trade_callback: Optional[Callable[[float, float, bool], None]] = None,
        on_heartbeat_callback: Optional[Callable[[], None]] = None,
    ):
        self.ws_url = ws_url
        self.market_index = market_index
        self.on_orderbook = on_orderbook_callback
        self.on_trade = on_trade_callback
        self.on_heartbeat = on_heartbeat_callback
        self.is_running = False
        self.current_book = L2OrderBook(market_index=market_index)
        self.depth_book = MicrostructureDepthBook(market_index=market_index)
        global_depth_vwap_engine.books[market_index] = self.depth_book
        # Seconds epoch of last order_book / depth load. 0 means never received.
        self.last_update_ts: float = 0.0

    async def start(self):
        """Runs the WebSocket subscription and event processing loop with auto-reconnect."""
        self.is_running = True
        logger.info(f"[WS] Connecting to Lighter WebSocket at {self.ws_url}...")

        while self.is_running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url, heartbeat=30.0) as ws:
                        logger.info("[WS] Connected. Subscribing to market channels...")

                        # 1. Subscribe to order_book channel
                        book_sub = {
                            "type": "subscribe",
                            "channel": f"order_book:{self.market_index}",
                        }
                        await ws.send_json(book_sub)

                        # 2. Subscribe to trade channel
                        trade_sub = {
                            "type": "subscribe",
                            "channel": f"trade:{self.market_index}",
                        }
                        await ws.send_json(trade_sub)

                        # Start background ping task
                        ping_task = asyncio.create_task(self._ping_loop(ws))

                        try:
                            async for msg in ws:
                                if not self.is_running:
                                    break

                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    self._handle_message(msg.data)
                                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                    logger.warning("[WS] WebSocket closed or error received.")
                                    break
                        finally:
                            ping_task.cancel()

            except Exception as e:
                logger.warning(f"[WS] Connection error: {e}. Reconnecting in 3 seconds...")
                await asyncio.sleep(3.0)

    async def _ping_loop(self, ws: aiohttp.ClientWebSocketResponse):
        """Sends application-level ping frame every 60 seconds."""
        while self.is_running and not ws.closed:
            try:
                await asyncio.sleep(60.0)
                await ws.send_json({"type": "ping"})
            except asyncio.CancelledError:
                break
            except Exception:
                break

    def _handle_message(self, raw_text: str):
        """Parses incoming WebSocket message JSON."""
        if self.on_heartbeat:
            self.on_heartbeat()

        try:
            data = json.loads(raw_text)
        except Exception:
            return

        msg_type = data.get("type", "")
        channel = data.get("channel", "")

        # Handle pong
        if msg_type == "pong":
            return

        # Handle Orderbook update
        if f"order_book:{self.market_index}" in channel or "order_book" in channel:
            ob_data = data.get("order_book", {})
            raw_bids = ob_data.get("bids", [])
            raw_asks = ob_data.get("asks", [])

            bids = [
                OrderBookLevel(price=float(b["price"]), size=float(b["size"]))
                for b in raw_bids
                if "price" in b and "size" in b
            ]
            asks = [
                OrderBookLevel(price=float(a["price"]), size=float(a["size"]))
                for a in raw_asks
                if "price" in a and "size" in a
            ]

            # Ensure proper sorting
            bids.sort(key=lambda x: x.price, reverse=True)
            asks.sort(key=lambda x: x.price, reverse=False)

            self.current_book = L2OrderBook(
                market_index=self.market_index,
                bids=bids,
                asks=asks,
                timestamp=time.time(),
                nonce=ob_data.get("nonce", 0),
            )
            self.depth_book.load_snapshot(
                bids=[(b.price, b.size) for b in bids],
                asks=[(a.price, a.size) for a in asks],
                nonce=ob_data.get("nonce", 0),
            )
            self.mark_book_update(self.current_book.timestamp)

            if self.on_orderbook:
                self.on_orderbook(self.current_book)

        # Handle Public Trade update
        elif f"trade:{self.market_index}" in channel or "trade" in channel:
            trades = data.get("trades", [])
            if isinstance(data.get("trade"), dict):
                trades = [data["trade"]]

            for t in trades:
                if "price" in t and "size" in t:
                    p = float(t["price"])
                    s = float(t["size"])
                    is_ask = t.get("is_maker_ask", False)
                    if self.on_trade:
                        self.on_trade(p, s, is_ask)

    def mark_book_update(self, ts: Optional[float] = None) -> None:
        """Records last L2/depth load time. Trades and pongs must not call this."""
        self.last_update_ts = float(ts if ts is not None else time.time())

    def book_age_ms(self) -> float:
        """Age of the last order_book/depth update in milliseconds. inf if never updated."""
        if self.last_update_ts <= 0:
            return float("inf")
        return max(0.0, (time.time() - self.last_update_ts) * 1000.0)

    def stop(self):
        """Stops the WebSocket streamer."""
        self.is_running = False
