#!/usr/bin/env python3
"""
Lighter DEX News Catalyst & Manual Quick-Snipe Execution Engine
==============================================================
Features:
- Sub-5ms Regex NLP Catalyst Classifier for breaking news
- One-Tap / Text-Triggered Manual Max-Size Entries ('btc', 'eth', 'short eth')
- Automated Multi-Stage Take-Profit (TP) & Trailing Stop-Loss (SL) Engine
- zkLighter Mainnet Execution with Max Collateral Margin
- Instant Telegram Alerts & Remote Trade Management
"""

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aiohttp
from dotenv import load_dotenv

from news_pipeline import NewsPipeline, NormalizedNewsEvent
from news_sources import NewsSourceRegistry, NewsSourceScheduler
from news_markets import MarketRegistry, TickerCache
from news_lifecycle import PositionBook, PositionClock, TradeIntentQueue
from news_observability import AuditLog, NewsMetrics
from lighter_news_risk import LighterNewsRiskGate, MarketSnapshot, live_execution_allowed
from trade_ledger import TradeLedger
from treenews_ws import TreeNewsWebSocketClient
from cross_exchange_momentum import CrossExchangeMomentumFilter, MomentumConfirmation
from depth_vwap_engine import (
    DepthVWAPEngine,
    MicrostructureDepthBook,
    calculate_vwap,
    liquidity_adjusted_size,
    global_depth_vwap_engine,
)

load_dotenv(Path(__file__).with_name(".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
try:
    _file_handler = logging.FileHandler(Path(__file__).with_name("sniper_app.log"), encoding="utf-8")
    _file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(_file_handler)
except OSError:
    pass
logger = logging.getLogger("LighterNewsSniper")


def unpack_signer_result(result: Any) -> Tuple[Any, Optional[str]]:
    """SignerClient returns (tx, resp, err) today; older code expected (tx_hash, err)."""
    if result is None:
        return None, "empty signer result"
    if not isinstance(result, (tuple, list)):
        return result, None
    if len(result) >= 3:
        tx, resp, err = result[0], result[1], result[2]
        return (resp if resp is not None else tx), err
    if len(result) == 2:
        return result[0], result[1]
    return result[0], None


def signer_tx_id(resp: Any) -> str:
    if resp is None:
        return ""
    for attr in ("tx_hash", "hash", "txHash"):
        value = getattr(resp, attr, None)
        if value:
            return str(value)
    if isinstance(resp, dict):
        for key in ("tx_hash", "hash", "txHash"):
            if resp.get(key):
                return str(resp[key])
    return str(resp)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class NewsItem:
    source: str
    headline: str
    body: str = ""
    timestamp: float = field(default_factory=time.time)
    url: str = ""


@dataclass
class CatalystSignal:
    news_id: str
    headline: str
    target_asset: str
    market_index: int
    sentiment: str  # "BULLISH" or "BEARISH"
    conviction_score: float
    matched_keywords: List[str]


@dataclass
class ActivePosition:
    position_id: str
    asset: str
    market_index: int
    side: str  # "BUY/LONG" or "SELL/SHORT"
    entry_price: float
    size_eth: float
    notional_usd: float
    tp_pct: float = 2.5
    sl_pct: float = 1.5
    highest_price: float = 0.0
    lowest_price: float = float("inf")
    entry_time: float = field(default_factory=time.time)
    is_active: bool = True
    tp_price: float = 0.0
    sl_price: float = 0.0
    ordered_size: float = 0.0
    exchange_tp: bool = False
    exchange_sl: bool = False
    max_hold_seconds: float = 2700.0
    trail_arm_pct: float = 1.5
    trail_gap_pct: float = 1.0
    tp_client_index: int = 0
    sl_client_index: int = 0
    tp_order_index: int = 0
    sl_order_index: int = 0
    exchange_sl_price: float = 0.0
    last_sl_amend_ts: float = 0.0
    pending_sl_amend: bool = False
    last_protect_attempt: float = 0.0
    original_size: float = 0.0
    tp_hits: int = 0
    atr_multiplier: float = 1.0
    volatility_expanded: bool = False
    catalyst_headline: str = ""
    catalyst_type: str = ""


# =============================================================================
# CATALYST CLASSIFIER
# =============================================================================

class CatalystClassifier:
    """Classifies breaking crypto news with ultra-low latency regex rules."""

    CATALYSTS = [
        {
            "pattern": r"(?=.*\b(trump|donald\s*trump|potus)\b)(?=.*\b(hyperliquid|hype)\b)",
            "target": "HYPE",
            "market_index": 0,
            "sentiment": "BULLISH",
            "conviction": 0.98,
        },
        {
            "pattern": r"(?=.*\b(trump|donald\s*trump|white\s*house)\b)(?=.*\b(crypto|bitcoin|btc|ethereum|eth|reserve)\b)",
            "target": "ETH",
            "market_index": 0,
            "sentiment": "BULLISH",
            "conviction": 0.90,
        },
        {
            "pattern": r"(?=.*\b(sec|gary\s*gensler)\b)(?=.*\b(approv(ed|es|al)|etf|settlement)\b)",
            "target": "ETH",
            "market_index": 0,
            "sentiment": "BULLISH",
            "conviction": 0.95,
        },
        {
            "pattern": r"(?=.*\b(binance|coinbase|robinhood)\b)(?=.*\b(list(s|ing|ed)?|launch(es)?)\b)",
            "target": "ETH",
            "market_index": 0,
            "sentiment": "BULLISH",
            "conviction": 0.85,
        },
        {
            "pattern": r"(?=.*\b(hack|exploit|drained|stolen|breach|vulnerability)\b)(?=.*\b(bridge|dex|lighter|protocol|millions)\b)",
            "target": "ETH",
            "market_index": 0,
            "sentiment": "BEARISH",
            "conviction": 0.95,
        },
    ]

    def __init__(self, max_news_age_sec: float = 60.0, min_conviction: float = 0.0, fingerprint_window_sec: float = 900.0):
        self.max_news_age_sec = max_news_age_sec
        self.min_conviction = min_conviction
        self.fingerprint_window_sec = fingerprint_window_sec
        self.seen_headlines: set = set()
        self.story_fingerprints: List[Tuple[str, str, set, float]] = []
        self.compiled_rules = [
            (re.compile(c["pattern"], re.IGNORECASE), c) for c in self.CATALYSTS
        ]

    def _prune_fingerprints(self, now: float) -> None:
        cutoff = now - self.fingerprint_window_sec
        self.story_fingerprints = [fp for fp in self.story_fingerprints if fp[3] >= cutoff]

    def _extract_tokens(self, text: str) -> set:
        words = set(re.findall(r"[a-z0-9]+", text.lower()))
        stopwords = {
            "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
            "and", "or", "as", "is", "are", "was", "were", "it", "this", "that", "be", "has", "have"
        }
        return words - stopwords

    def is_duplicate_fingerprint(self, target_asset: str, sentiment: str, text: str, now: Optional[float] = None) -> bool:
        ts = now if now is not None else time.time()
        self._prune_fingerprints(ts)
        tokens = self._extract_tokens(text)
        for cached_target, cached_sentiment, cached_tokens, fp_ts in self.story_fingerprints:
            if cached_target.upper() == target_asset.upper() and cached_sentiment == sentiment:
                union = tokens | cached_tokens
                jaccard = len(tokens & cached_tokens) / len(union) if union else 1.0
                if jaccard >= 0.35 or len(tokens & cached_tokens) >= 3:
                    return True
        return False

    def process_news(self, news: NewsItem) -> Optional[CatalystSignal]:
        now = time.time()
        if now - news.timestamp > self.max_news_age_sec:
            return None

        clean_title = news.headline.strip().lower()
        if clean_title in self.seen_headlines:
            return None

        self._prune_fingerprints(now)
        full_text = f"{news.headline} {news.body}".strip()
        tokens = self._extract_tokens(full_text)

        for regex, rule in self.compiled_rules:
            if regex.search(full_text) and rule["conviction"] >= self.min_conviction:
                target = rule["target"]
                sentiment = rule["sentiment"]

                # Check story fingerprint cache (15-minute lockout)
                for cached_target, cached_sentiment, cached_tokens, fp_ts in self.story_fingerprints:
                    if cached_target.upper() == target.upper() and cached_sentiment == sentiment:
                        union = tokens | cached_tokens
                        jaccard = len(tokens & cached_tokens) / len(union) if union else 1.0
                        if jaccard >= 0.35 or len(tokens & cached_tokens) >= 3:
                            return None

                self.seen_headlines.add(clean_title)
                self.story_fingerprints.append((target, sentiment, tokens, now))
                return CatalystSignal(
                    news_id=f"cat_{int(now*1000)}",
                    headline=news.headline,
                    target_asset=rule["target"],
                    market_index=rule["market_index"],
                    sentiment=rule["sentiment"],
                    conviction_score=rule["conviction"],
                    matched_keywords=list(regex.findall(full_text)),
                )
        return None


# =============================================================================
# MAX-SIZE & TAKE-PROFIT EXECUTION ENGINE
# =============================================================================

class MaxSizeExecutionEngine:
    """Manages Max-Size orders, dynamic margin sizing, and Take-Profit watchdog."""

    def __init__(
        self,
        is_live: bool = True,
        max_margin_utilization_pct: float = 85.0,
        slippage_tolerance_pct: float = 0.5,
        default_tp_pct: float = 2.5,
        default_sl_pct: float = 1.5,
    ):
        self.is_live = bool(is_live)
        self.max_margin_utilization_pct = max_margin_utilization_pct
        self.slippage_tolerance_pct = slippage_tolerance_pct
        self.default_tp_pct = default_tp_pct
        self.default_sl_pct = default_sl_pct

        self.base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai")
        self.account_index = int(os.getenv("LIGHTER_ACCOUNT_INDEX", 737649))
        self.api_key_index = int(os.getenv("LIGHTER_API_KEY_INDEX", 5))
        self.api_private_key = os.getenv("LIGHTER_API_PRIVATE_KEY", "")

        self.signer_client = None
        self.active_positions: Dict[str, ActivePosition] = {}
        self.market_meta: Dict[str, Dict[str, Any]] = {}
        self.depth_engine = global_depth_vwap_engine
        from volatility_adaptive_exits import get_volatility_engine
        self.volatility_engine = get_volatility_engine()
        self._http: Optional[aiohttp.ClientSession] = None
        self._order_lock = asyncio.Lock()
        self._last_care_ts: float = 0.0
        self._cached_catalog: List[Dict[str, Any]] = []
        self._cached_positions: List[Dict[str, Any]] = []
        self._last_catalog_fetch_ts: float = 0.0
        self._last_positions_fetch_ts: float = 0.0
        self._last_cached_collateral: float = float(os.getenv("LIGHTER_FALLBACK_COLLATERAL", "5.5208"))
        self._collateral_cache_ts: float = 0.0
        self._spread_cache: Dict[int, Tuple[float, float]] = {}
        self.clock = PositionClock(os.getenv("NEWS_DB_PATH", str(Path(__file__).with_name("lighter_news.db"))))

    @staticmethod
    def _speed_mode() -> bool:
        return os.getenv("SPEED_MODE", "1").strip().lower() in {"1", "true", "yes", "on"}

    def _collateral_cache_ttl_sec(self) -> float:
        # Hot-path: reuse collateral aggressively (override via NEWS_COLLATERAL_CACHE_MS)
        ms = float(os.getenv("NEWS_COLLATERAL_CACHE_MS", "5000" if self._speed_mode() else "500"))
        return max(0.0, ms / 1000.0)

    def _fill_confirm_timeout_sec(self) -> float:
        default = "1.2" if self._speed_mode() else "8.0"
        return float(os.getenv("NEWS_FILL_CONFIRM_TIMEOUT", default))

    def _fill_poll_interval_sec(self) -> float:
        return float(os.getenv("NEWS_FILL_POLL_MS", "80" if self._speed_mode() else "400")) / 1000.0

    def _async_fill_confirm(self) -> bool:
        """Return after order ACK; confirm fill + protective exits in background."""
        default = "1" if self._speed_mode() else "0"
        return os.getenv("SPEED_ASYNC_FILL_CONFIRM", default).strip().lower() in {"1", "true", "yes", "on"}

    def _skip_vwap_guard(self) -> bool:
        default = "1" if self._speed_mode() else "0"
        return os.getenv("SPEED_SKIP_VWAP", default).strip().lower() in {"1", "true", "yes", "on"}

    def cached_collateral_usd(self) -> Optional[float]:
        val = float(getattr(self, "_last_cached_collateral", 0.0) or 0.0)
        return val if val > 0 else None

    async def _ensure_signer(self):
        if self.is_live and self.signer_client is None and self.api_private_key and self.account_index > 0:
            try:
                import lighter
                self.signer_client = lighter.SignerClient(
                    url=self.base_url,
                    account_index=self.account_index,
                    api_private_keys={self.api_key_index: self.api_private_key},
                )
                logger.info(f"⚡ [EXEC] SignerClient connected for Account #{self.account_index}")
            except Exception as e:
                logger.error("❌ [EXEC] SignerClient init error: %s: %s", type(e).__name__, e or "no message")

    async def prewarm(self) -> None:
        """Warm signer + HTTP + collateral before the first catalyst (cuts cold-start RTT)."""
        await self._ensure_signer()
        await self._http_session()
        await self.fetch_available_collateral_usd(force=True)
        logger.info("⚡ [SPEED] Executor prewarmed (signer=%s collateral_cache=$%.2f)",
                    bool(self.signer_client), self._last_cached_collateral)

    async def _http_session(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=40,
                enable_cleanup_closed=True,
                keepalive_timeout=75.0,
                ttl_dns_cache=300,
                happy_eyeballs_delay=0.05,
            )
            # Aggressive timeouts on the money path
            total = 3.0 if self._speed_mode() else 6.0
            connect = 1.0 if self._speed_mode() else 2.0
            sock_read = 2.0 if self._speed_mode() else 4.0
            self._http = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=total, connect=connect, sock_read=sock_read),
            )
        return self._http

    def _select_subaccount(self, sub_accs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for acc in sub_accs:
            try:
                if int(acc.get("index", acc.get("account_index", -1))) == self.account_index:
                    return acc
            except (TypeError, ValueError):
                continue
        # Fallback: pick the sub-account with the highest collateral (index field may be absent)
        best: Optional[Dict[str, Any]] = None
        best_collat = 0.0
        for acc in sub_accs:
            collat = self._parse_collateral(acc)
            if collat is not None and collat > best_collat:
                best_collat = collat
                best = acc
        return best

    def _parse_collateral(self, acc: Dict[str, Any]) -> Optional[float]:
        for key in ("collateral", "available_balance", "available_collateral", "total_collateral", "balance"):
            value = acc.get(key)
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    async def fetch_available_collateral_usd(self, force: bool = False) -> Optional[float]:
        """Fetches the configured sub-account collateral with short TTL cache (hot-path)."""
        wallet = os.getenv("WALLET_ADDRESS", "").strip()
        if not wallet:
            logger.error("Live collateral query failed: WALLET_ADDRESS is not set")
            return None

        ttl = self._collateral_cache_ttl_sec()
        cache_ts = float(getattr(self, "_collateral_cache_ts", 0.0) or 0.0)
        age = time.time() - cache_ts
        cached = float(getattr(self, "_last_cached_collateral", 0.0) or 0.0)
        fallback_default = float(os.getenv("LIGHTER_FALLBACK_COLLATERAL", "5.5208"))
        cache_verified = cache_ts > 0 and cached > fallback_default
        if not force and ttl > 0 and age < ttl and cache_verified:
            return cached

        if not hasattr(self, "_last_cached_collateral"):
            self._last_cached_collateral = fallback_default
        try:
            session = await self._http_session()
            # Collateral fetch must not use the 2s speed-path timeout — false low reads block all fills.
            http_to = aiohttp.ClientTimeout(total=4.0)

            def _store_collateral(collat: float) -> float:
                self._last_cached_collateral = collat
                self._collateral_cache_ts = time.time()
                return collat

            # 1. Direct query by subaccount index (matches check_positions_detail.py)
            url_idx = f"{self.base_url}/api/v1/account?by=index&value={self.account_index}"
            async with session.get(url_idx, timeout=http_to) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    accs = data.get("accounts") or []
                    for ac in accs:
                        collat = self._parse_collateral(ac)
                        if collat is not None and collat > 0:
                            return _store_collateral(collat)
                    collat = self._parse_collateral(data)
                    if collat is not None and collat > 0:
                        return _store_collateral(collat)

            # 2. Fallback: Query by L1 Wallet address
            if wallet:
                url_wallet = f"{self.base_url}/api/v1/accountsByL1Address?l1_address={wallet}"
                async with session.get(url_wallet, timeout=http_to) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        sub_accs = data.get("sub_accounts") or data.get("accounts") or data.get("data") or []
                        if isinstance(sub_accs, dict):
                            sub_accs = sub_accs.get("sub_accounts") or [sub_accs]
                        acc = self._select_subaccount(list(sub_accs))
                        if acc is not None:
                            collat = self._parse_collateral(acc)
                            if collat is not None and collat > 0:
                                return _store_collateral(collat)

            if cache_verified:
                return cached
            logger.warning("Live collateral query failed; using fallback $%.2f", self._last_cached_collateral)
            return self._last_cached_collateral
        except Exception as e:
            if cache_verified:
                logger.debug("Live collateral query using cached value ($%.2f): %s", cached, e)
                return cached
            logger.warning("Live collateral query failed ($%.2f fallback): %s", self._last_cached_collateral, e)
            return self._last_cached_collateral


    def _book_to_snapshot(self, asset: str, book: Dict[str, Any]) -> Optional[MarketSnapshot]:
        try:
            idx = int(book.get("market_id", book.get("market_index", -1)))
        except (TypeError, ValueError):
            return None
        last = float(book.get("last_trade_price") or book.get("mark_price") or book.get("index_price") or 0)
        mark = float(book.get("mark_price") or last)
        spread_bps = abs(mark - last) / last * 10_000.0 if last else 0.0
        size_decimals = self._int_or(book.get("supported_size_decimals", book.get("size_decimals")), 4)
        price_decimals = self._int_or(book.get("supported_price_decimals", book.get("price_decimals")), 2)
        min_base = float(book.get("min_base_amount") or 0.0)
        min_quote = float(book.get("min_quote_amount") or 0.0)
        self.market_meta[asset.upper()] = {
            "market_index": idx,
            "size_decimals": size_decimals,
            "price_decimals": price_decimals,
            "min_base_amount": min_base,
            "min_quote_amount": min_quote,
        }
        if last <= 0:
            return None
        return MarketSnapshot(
            asset.upper(),
            last,
            spread_bps=spread_bps,
            timestamp=time.time(),
            size_decimals=size_decimals,
            price_decimals=price_decimals,
            min_base_amount=min_base,
            market_index=idx,
        )

    def _meta(self, asset: str) -> Dict[str, Any]:
        if asset.upper() not in self.market_meta:
            try:
                p = Path(__file__).with_name("lighter_universe.json")
                if p.exists():
                    import json
                    disk_data = json.loads(p.read_text(encoding="utf-8"))
                    books = disk_data.get("order_books") or disk_data.get("order_book_details") or []
                    for b in books:
                        sym = str(b.get("symbol") or "").upper()
                        if sym:
                            idx = int(b.get("market_id", b.get("market_index", -1)))
                            s_dec = self._int_or(b.get("supported_size_decimals", b.get("size_decimals")), 4)
                            p_dec = self._int_or(b.get("supported_price_decimals", b.get("price_decimals")), 2)
                            self.market_meta[sym] = {
                                "market_index": idx,
                                "size_decimals": s_dec,
                                "price_decimals": p_dec,
                                "min_base_amount": float(b.get("min_base_amount") or 0.0),
                                "min_quote_amount": float(b.get("min_quote_amount") or 0.0),
                            }
            except Exception:
                pass
        defaults = {"size_decimals": 4, "price_decimals": 2, "min_base_amount": 0.0, "market_index": 0}
        merged = dict(defaults)
        merged.update(self.market_meta.get(asset.upper(), {}))
        return merged

    async def fetch_order_catalog(self) -> List[Dict[str, Any]]:
        now = time.time()
        # Tier-1 Memory Cache: Serve fast sub-millisecond cached catalog if fresh (<2s)
        if self._cached_catalog and (now - self._last_catalog_fetch_ts) < 2.0:
            return self._cached_catalog

        try:
            session = await self._http_session()
            async with session.get(f"{self.base_url}/api/v1/orderBookDetails") as resp:
                if resp.status != 200:
                    async with session.get(f"{self.base_url}/api/v1/orderBooks") as resp2:
                        resp = resp2
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    books = data.get("order_book_details") or data.get("order_books") or data.get("data") or []
                    if isinstance(books, dict):
                        books = books.get("order_book_details") or [books]
                    books = list(books)
                    if books:
                        for book in books:
                            symbol = str(book.get("symbol") or "").upper()
                            if symbol:
                                self._book_to_snapshot(symbol, book)
                        self._cached_catalog = books
                        self._last_catalog_fetch_ts = now
                        return books
        except Exception as e:
            logger.debug("Market catalog live fetch transient drop: %s", e)

        # Tier-2 Fallback: Return in-memory cache if available
        if self._cached_catalog:
            return self._cached_catalog

        # Tier-3 Fallback: Load from lighter_universe.json disk cache
        try:
            p = Path(__file__).with_name("lighter_universe.json")
            if p.exists():
                import json
                disk_data = json.loads(p.read_text(encoding="utf-8"))
                books = disk_data.get("order_book_details") or disk_data.get("order_books") or []
                if books:
                    self._cached_catalog = list(books)
                    return self._cached_catalog
        except Exception:
            pass

        return []

    async def fetch_market_snapshot(self, asset: str, market_index: int) -> Optional[MarketSnapshot]:
        # Tier-1: Live L2 Depth Book mid-price
        try:
            depth_book = await self.fetch_orderbook_depth(market_index)
            if depth_book and depth_book.mid_price > 0:
                snap = MarketSnapshot(
                    asset=asset.upper(),
                    price=depth_book.mid_price,
                    spread_bps=depth_book.spread_bps,
                    timestamp=time.time(),
                    market_index=market_index,
                )
                meta = self._meta(asset)
                snap.size_decimals = meta.get("size_decimals", 4)
                snap.price_decimals = meta.get("price_decimals", 2)
                return snap
        except Exception:
            pass

        # Tier-2: Recent Trades price
        try:
            session = await self._http_session()
            url = f"{self.base_url}/api/v1/recentTrades?market_id={market_index}&limit=5"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    trades = data.get("trades") or []
                    if trades:
                        price = float(trades[0].get("price") or 0.0)
                        if price > 0:
                            return MarketSnapshot(
                                asset=asset.upper(),
                                price=price,
                                spread_bps=10.0,
                                timestamp=time.time(),
                                market_index=market_index,
                            )
        except Exception:
            pass

        # Tier-3: Order Catalog
        books = await self.fetch_order_catalog()
        snapshots = self.snapshots_from_catalog(books, [(asset, market_index)])
        return snapshots.get(asset.upper())

    async def fetch_orderbook_depth(self, market_index: int) -> MicrostructureDepthBook:
        """Fetches live L2 depth orderbook from Lighter API and updates in-memory engine."""
        try:
            session = await self._http_session()
            url = f"{self.base_url}/api/v1/orderBookOrders?market_id={market_index}&limit=50"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    bids = data.get("bids") or []
                    asks = data.get("asks") or []
                    return self.depth_engine.update_from_raw_l2(market_index, bids, asks)
        except Exception as e:
            logger.debug("fetch_orderbook_depth error: %s", e)
        return self.depth_engine.get_or_create_book(market_index)

    def snapshots_from_catalog(self, books: List[Dict[str, Any]], wanted: List[Tuple[str, int]]) -> Dict[str, MarketSnapshot]:
        by_symbol: Dict[str, Dict[str, Any]] = {}
        by_id: Dict[int, Dict[str, Any]] = {}
        for book in books:
            symbol = str(book.get("symbol", "")).upper()
            if symbol:
                by_symbol[symbol] = book
            try:
                by_id[int(book.get("market_id", book.get("market_index", -1)))] = book
            except (TypeError, ValueError):
                continue
        out: Dict[str, MarketSnapshot] = {}
        for asset, market_index in wanted:
            book = by_symbol.get(asset.upper()) or by_id.get(market_index)
            if not book:
                continue
            snapshot = self._book_to_snapshot(asset, book)
            if snapshot:
                out[asset.upper()] = snapshot
        return out

    def calculate_max_order_size(
        self,
        collateral_usd: float,
        current_price_usd: float,
        conviction: Optional[float] = None,
        margin_utilization_pct: Optional[float] = None,
        max_trade_usd: Optional[float] = None,
    ) -> float:
        if margin_utilization_pct is not None:
            utilization = margin_utilization_pct
        elif conviction is not None:
            from trade_exits import dynamic_kelly_margin
            utilization = dynamic_kelly_margin(conviction)
        else:
            utilization = self.max_margin_utilization_pct
        usable_usd = collateral_usd * (utilization / 100.0)
        if max_trade_usd is not None:
            usable_usd = min(usable_usd, max_trade_usd)
        size_eth = usable_usd / max(1e-6, current_price_usd)
        return round(size_eth, 8)

    def _int_or(self, value: Any, default: int) -> int:
        if value is None or value == "":
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


    def ensure_exit_prices(self, pos: ActivePosition) -> None:
        """Every position always has local TP and SL prices for the watchdog with volatility adaptation."""
        from trade_exits import TP_LADDER_LEVELS, policy_for, tp_sl_prices, scale_tp_price
        from volatility_adaptive_exits import get_volatility_engine

        engine = getattr(self, "volatility_engine", None) or get_volatility_engine()
        vol_state = engine.get_state(pos.asset) if engine else None
        mult = getattr(pos, "atr_multiplier", 1.0) or 1.0
        if mult == 1.0 and vol_state and vol_state.atr_multiplier > 1.0:
            mult = vol_state.atr_multiplier
            pos.atr_multiplier = mult
            pos.volatility_expanded = vol_state.is_violent_catalyst

        policy = policy_for(
            pos.asset,
            override_tp=pos.tp_pct or None,
            override_sl=pos.sl_pct or None,
            atr_multiplier=mult,
            news_headline=getattr(pos, "catalyst_headline", None),
            catalyst_type=getattr(pos, "catalyst_type", None),
        )
        pos.tp_pct = pos.tp_pct or policy.tp_pct
        pos.sl_pct = pos.sl_pct or policy.sl_pct
        pos.max_hold_seconds = pos.max_hold_seconds or policy.max_hold_seconds
        pos.trail_arm_pct = pos.trail_arm_pct or policy.trail_arm_pct
        pos.trail_gap_pct = policy.trail_gap_pct if (pos.volatility_expanded or not pos.trail_gap_pct) else pos.trail_gap_pct
        if pos.entry_price <= 0:
            return
        tp, sl = tp_sl_prices(pos.side, pos.entry_price, policy)
        if not pos.original_size:
            pos.original_size = pos.size_eth or pos.ordered_size
        nxt = (pos.tp_hits or 0) + 1
        if nxt <= TP_LADDER_LEVELS:
            pos.tp_price = scale_tp_price(pos.side, pos.entry_price, policy, nxt, atr_multiplier=mult)
        else:
            pos.tp_price = 0.0
            pos.trail_gap_pct = pos.trail_gap_pct or 1.0
        if not pos.sl_price:
            pos.sl_price = sl

    async def _refresh_nonce(self) -> None:
        manager = getattr(self.signer_client, "nonce_manager", None)
        if manager is None:
            return
        try:
            await manager.async_hard_refresh_nonce(self.api_key_index)
        except TypeError:
            await manager.async_hard_refresh_nonce()
        except Exception as e:
            logger.warning("Nonce refresh failed: %s", e)

    async def _submit_live_order(
        self,
        asset: str,
        market_index: int,
        size: float,
        price: float,
        is_ask: bool,
        reduce_only: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        await self._ensure_signer()
        if not self.signer_client:
            return None, "SignerClient unavailable"
        async with self._order_lock:
            return await self._submit_live_order_locked(asset, market_index, size, price, is_ask, reduce_only)

    async def _submit_live_order_locked(
        self,
        asset: str,
        market_index: int,
        size: float,
        price: float,
        is_ask: bool,
        reduce_only: bool = False,
    ) -> Tuple[Optional[str], Optional[str]]:
        meta = self._meta(asset)
        size_decimals = self._int_or(meta.get("size_decimals"), 4)
        price_decimals = self._int_or(meta.get("price_decimals"), 2)

        # Hard safety clamp: Never allow a new entry to exceed NEWS_MAX_TRADE_USD ($250.00)
        if not reduce_only and price > 0:
            max_usd = float(os.getenv("NEWS_MAX_TRADE_USD", "250.0"))
            max_allowed_size = (max_usd * 1.05) / price
            if size > max_allowed_size:
                logger.critical(
                    "🚨 [HARD SIZING CLAMP] Prevented oversized order on %s: requested size %s ($%.2f USD) clamped to %s ($%.2f USD)",
                    asset, size, size * price, max_allowed_size, max_usd,
                )
                size = max_allowed_size
                if size_decimals == 0:
                    size = float(int(size))
                else:
                    size = round(size, size_decimals)

        size_int = int(round(size * (10 ** size_decimals)))
        price_int = int(round(price * (10 ** price_decimals)))
        if size_int <= 0:
            return None, f"size {size} rounds to 0 with {size_decimals} decimals"
        last_err = "order failed"
        for attempt in range(2):
            client_order_index = int(time.time() * 1000) % 100_000_000
            try:
                if hasattr(self.signer_client, "create_market_order"):
                    result = await self.signer_client.create_market_order(
                        market_index=market_index,
                        client_order_index=client_order_index,
                        base_amount=size_int,
                        avg_execution_price=price_int,
                        is_ask=is_ask,
                        reduce_only=reduce_only,
                    )
                else:
                    result = await self.signer_client.create_order(
                        market_index=market_index,
                        client_order_index=client_order_index,
                        base_amount=size_int,
                        price=price_int,
                        is_ask=is_ask,
                        order_type=getattr(self.signer_client, "ORDER_TYPE_MARKET", 1),
                        time_in_force=getattr(self.signer_client, "ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL", 1),
                    )
            except Exception as e:
                last_err = f"{type(e).__name__}: {e or 'no message'}"
                if "invalid nonce" in last_err.lower() and attempt == 0:
                    await self._refresh_nonce()
                    await asyncio.sleep(0.05 if self._speed_mode() else 0.2)
                    continue
                return None, last_err
            resp, err = unpack_signer_result(result)
            if err:
                last_err = str(err)
                if "invalid nonce" in last_err.lower() and attempt == 0:
                    await self._refresh_nonce()
                    await asyncio.sleep(0.05 if self._speed_mode() else 0.2)
                    continue
                return None, last_err
            return signer_tx_id(resp), None
        return None, last_err

    def parse_account_position(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Lighter sends abs `position` plus `sign` (1 long / -1 short). market_id 0 is ETH."""
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
        try:
            open_n = int(item.get("open_order_count") or item.get("position_tied_order_count") or item.get("pending_order_count") or 0)
        except (TypeError, ValueError):
            open_n = 0
        return {
            "symbol": symbol,
            "market_index": market_id,
            "size": abs(size),
            "signed": abs(size) * (1 if sign >= 0 else -1),
            "side": "BUY/LONG" if sign >= 0 else "SELL/SHORT",
            "entry_price": entry,
            "open_order_count": open_n,
        }

    async def fetch_account_positions(self) -> List[Dict[str, Any]]:
        now = time.time()
        if self._cached_positions and (now - self._last_positions_fetch_ts) < 1.0:
            return self._cached_positions

        try:
            session = await self._http_session()
            url = f"{self.base_url}/api/v1/account?by=index&value={self.account_index}&active_only=true"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    accounts = data.get("accounts") or data.get("data") or ([data] if isinstance(data, dict) else [])
                    positions: List[Dict[str, Any]] = []
                    for acc in accounts if isinstance(accounts, list) else [accounts]:
                        if not isinstance(acc, dict):
                            continue
                        collat = self._parse_collateral(acc)
                        if collat is not None and collat > 0:
                            self._last_cached_collateral = collat
                            self._collateral_cache_ts = time.time()
                        raw = acc.get("positions") or acc.get("position") or []
                        if isinstance(raw, dict):
                            raw = list(raw.values())
                        for item in raw:
                            parsed = self.parse_account_position(item)
                            if parsed:
                                positions.append(parsed)
                    self._cached_positions = positions
                    self._last_positions_fetch_ts = now
                    return positions
        except Exception as e:
            logger.debug("Account position fetch transient drop: %s", e)

        return self._cached_positions

    async def sync_and_adopt_all_live_positions(self) -> Dict[str, float]:
        """Automatically adopts all open on-chain positions from zkLighter into the TP/SL watchdog."""
        prices: Dict[str, float] = {}
        try:
            live = await self.fetch_account_positions()
            books = await self.fetch_order_catalog()
            catalog_prices: Dict[str, float] = {}
            for b in books:
                sym = str(b.get("symbol", "")).upper()
                last_p = float(b.get("last_trade_price") or b.get("mark_price") or b.get("index_price") or 0)
                if sym and last_p > 0:
                    catalog_prices[sym] = last_p

            for item in live:
                sym = str(item.get("symbol") or "").upper()
                size = float(item.get("size") or 0)
                if not sym or size <= 0:
                    continue
                side = item.get("side") or "BUY/LONG"
                entry = float(item.get("entry_price") or 0)
                mkt_idx = int(item.get("market_index") or 0)
                mark = catalog_prices.get(sym, entry)
                notional = size * (entry if entry > 0 else mark)
                if notional < 1.0:
                    continue
                if mark > 0:
                    prices[sym] = mark
                open_n = int(item.get("open_order_count") or item.get("position_tied_order_count") or 0)

                pos = self.existing_position(sym)
                if pos is None or not pos.is_active:
                    from trade_exits import policy_for
                    policy = policy_for(sym)
                    pos = ActivePosition(
                        position_id=f"adopted_{sym}_{mkt_idx}",
                        asset=sym,
                        market_index=mkt_idx,
                        side=side,
                        entry_price=entry if entry > 0 else (mark if mark > 0 else 1.0),
                        size_eth=size,
                        notional_usd=size * (entry if entry > 0 else mark),
                        tp_pct=policy.tp_pct or self.default_tp_pct or 2.5,
                        sl_pct=policy.sl_pct or 1.5,
                        is_active=True,
                    )
                    self.ensure_exit_prices(pos)
                    self.active_positions[pos.position_id] = pos
                    logger.info(
                        "🛡️ [ADOPTED POSITION] %s %s Size=%s @ $%.4f | TP: $%.4f (+%.1f%%) | SL: $%.4f (-%.1f%%)",
                        sym, side, size, pos.entry_price, pos.tp_price, pos.tp_pct, pos.sl_price, pos.sl_pct
                    )
                else:
                    pos.size_eth = size
                    self.ensure_exit_prices(pos)

                if open_n < 2 and self.is_live:
                    asyncio.create_task(self.sync_position_orders(pos, open_n))
        except Exception as e:
            logger.debug(f"Position adoption sync error: {e}")
        return prices

    def match_exchange_position(self, positions: List[Dict[str, Any]], asset: str, market_index: int = -1) -> Optional[Dict[str, Any]]:
        want = (asset or "").upper()
        if want:
            for item in positions:
                if item.get("symbol") == want:
                    return item
            return None
        for item in positions:
            if market_index not in (None, -1) and item.get("market_index") == market_index:
                return item
        return None

    async def wait_for_exchange_position(
        self,
        asset: str,
        market_index: int,
        timeout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        if timeout is None:
            timeout = self._fill_confirm_timeout_sec()
        poll = self._fill_poll_interval_sec()
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            found = self.match_exchange_position(await self.fetch_account_positions(), asset, market_index)
            if found:
                return found
            await asyncio.sleep(poll)
        return None

    async def fetch_spread_bps(self, market_index: int) -> float:
        try:
            now = time.time()
            cached = self._spread_cache.get(int(market_index))
            ttl = 0.35 if self._speed_mode() else 0.15
            if cached and (now - cached[0]) < ttl:
                return float(cached[1])
            session = await self._http_session()
            url = f"{self.base_url}/api/v1/orderBookOrders?market_id={market_index}&limit=1"
            async with session.get(url) as resp:
                if resp.status != 200:
                    return float(cached[1]) if cached else 0.0
                data = await resp.json(content_type=None)
            bids = data.get("bids") or []
            asks = data.get("asks") or []
            if not bids or not asks:
                return 0.0
            bid = float(bids[0].get("price") if isinstance(bids[0], dict) else bids[0][0])
            ask = float(asks[0].get("price") if isinstance(asks[0], dict) else asks[0][0])
            mid = (bid + ask) / 2.0
            if mid <= 0:
                return 0.0
            spread = abs(ask - bid) / mid * 10_000.0
            self._spread_cache[int(market_index)] = (now, spread)
            return spread
        except Exception:
            return 0.0

    def _extract_orders(self, data: Any) -> List[Dict[str, Any]]:
        orders: List[Dict[str, Any]] = []
        if data is None:
            return orders
        if isinstance(data, list):
            blobs = data
        elif isinstance(data, dict):
            blobs = data.get("orders") or data.get("open_orders") or data.get("pending_orders") or data.get("data") or data.get("accounts") or [data]
            if isinstance(blobs, dict):
                blobs = list(blobs.values())
        else:
            return orders
        for item in blobs:
            if not isinstance(item, dict):
                continue
            nested = item.get("orders") or item.get("open_orders") or item.get("pending_orders")
            if isinstance(nested, list):
                orders.extend(x for x in nested if isinstance(x, dict))
            elif isinstance(nested, dict):
                orders.extend(x for x in nested.values() if isinstance(x, dict))
            elif item.get("order_index") is not None or item.get("client_order_index") is not None or item.get("price") is not None:
                orders.append(item)
        return orders

    async def fetch_open_orders(self) -> List[Dict[str, Any]]:
        orders: List[Dict[str, Any]] = []
        try:
            session = await self._http_session()
            url = f"{self.base_url}/api/v1/account?by=index&value={self.account_index}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    orders.extend(self._extract_orders(await resp.json(content_type=None)))
        except Exception:
            pass
        try:
            session = await self._http_session()
            url = f"{self.base_url}/api/v1/accountActiveOrders?account_index={self.account_index}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    orders.extend(self._extract_orders(await resp.json(content_type=None)))
        except Exception:
            pass
        seen = set()
        uniq: List[Dict[str, Any]] = []
        for item in orders:
            key = (
                self._order_int(item, "market_id", "market_index"),
                self._order_int(item, "order_index", "order_id", "index", "client_order_index"),
            )
            if key in seen:
                continue
            seen.add(key)
            uniq.append(item)
        return uniq

    def existing_position(self, asset: str, market_index: Optional[int] = None) -> Optional[ActivePosition]:
        want = (asset or "").upper()
        for pos in self.active_positions.values():
            if not pos.is_active:
                continue
            # Ignore sub-minimum residual dust (< $10.00)
            if abs(getattr(pos, "notional_usd", 0.0)) < 10.0 and abs(getattr(pos, "size_eth", 0.0)) * getattr(pos, "entry_price", 0.0) < 10.0:
                continue
            if pos.asset.upper() == want:
                return pos
            # Market 0 is ETH's default; only treat a real catalog id as a duplicate slot.
            if market_index not in (None, 0, -1) and pos.market_index == market_index:
                return pos
        return None

    def _protect_fns(self):
        # Market trigger first (no extra GTT margin); limit GTT as fallback.
        tp_fns = [fn for fn in (
            getattr(self.signer_client, "create_tp_order", None),
            getattr(self.signer_client, "create_tp_limit_order", None),
        ) if fn]
        sl_fns = [fn for fn in (
            getattr(self.signer_client, "create_sl_order", None),
            getattr(self.signer_client, "create_sl_limit_order", None),
        ) if fn]
        return tp_fns, sl_fns

    def _order_int(self, item: Dict[str, Any], *keys: str) -> int:
        for key in keys:
            value = item.get(key)
            if value is None or value == "":
                continue
            try:
                return int(float(value))
            except (TypeError, ValueError):
                continue
        return 0

    async def verify_protective_exits(self, pos: ActivePosition, timeout: float = 6.0) -> Dict[str, Any]:
        deadline = time.time() + timeout
        found_tp = False
        found_sl = False
        while time.time() < deadline:
            orders = await self.fetch_open_orders()
            for item in orders:
                market_id = self._order_int(item, "market_id", "market_index")
                if market_id != pos.market_index:
                    continue
                client_idx = self._order_int(item, "client_order_index", "client_order_id")
                order_idx = self._order_int(item, "order_index", "order_id", "index")
                if pos.tp_client_index and client_idx == pos.tp_client_index:
                    found_tp = True
                    if order_idx:
                        pos.tp_order_index = order_idx
                elif pos.sl_client_index and client_idx == pos.sl_client_index:
                    found_sl = True
                    if order_idx:
                        pos.sl_order_index = order_idx
            if found_tp or found_sl:
                break
            await asyncio.sleep(0.5)
        pos.exchange_tp = found_tp or pos.exchange_tp
        pos.exchange_sl = found_sl or pos.exchange_sl
        return {"tp": pos.exchange_tp, "sl": pos.exchange_sl, "tp_idx": pos.tp_order_index, "sl_idx": pos.sl_order_index}

    async def place_protective_exits(self, pos: ActivePosition, tp_price: float, sl_price: float) -> Dict[str, Any]:
        from trade_exits import protect_limit_price

        self.ensure_exit_prices(pos)
        tp_price = pos.tp_price or tp_price
        sl_price = pos.sl_price or sl_price
        status = {"tp": False, "sl": False, "detail": "local watchdog only", "on_book": False}
        if self.is_live and self.signer_client is None:
            await self._ensure_signer()
        if not self.signer_client:
            status["detail"] = "local watchdog TP/SL armed (signer unavailable)"
            return status
        live = self.match_exchange_position(await self.fetch_account_positions(), pos.asset, pos.market_index)
        if live:
            pos.size_eth = float(live.get("size") or pos.size_eth)
            if live.get("market_index") not in (None, -1):
                pos.market_index = int(live["market_index"])
        try:
            await self.fetch_order_catalog()
        except Exception:
            pass
        is_ask = pos.side == "BUY/LONG"
        meta = self._meta(pos.asset)
        price_decimals = self._int_or(meta.get("price_decimals"), 2)
        size_decimals = self._int_or(meta.get("size_decimals"), 4)
        from trade_exits import partial_qty
        if not pos.original_size:
            pos.original_size = pos.size_eth or pos.ordered_size
        level = min(4, int(pos.tp_hits or 0) + 1)
        tp_qty = partial_qty(pos.original_size, pos.size_eth, level)
        sl_qty = pos.size_eth
        tp_size_int = int(tp_qty * (10 ** size_decimals))
        sl_size_int = int(sl_qty * (10 ** size_decimals))  # floor; size_decimals 0 is valid (XRP)
        size_int = sl_size_int
        if sl_size_int <= 0:
            status["detail"] = "local watchdog TP/SL armed (size too small for exchange)"
            logger.info("No exchange TP/SL for %s size=%s — watchdog will exit at TP/SL", pos.asset, pos.size_eth)
            return status
        tp_trigger = int(round(tp_price * (10 ** price_decimals)))
        sl_trigger = int(round(sl_price * (10 ** price_decimals)))
        tp_limit = int(round(protect_limit_price(pos.side, "tp", tp_price) * (10 ** price_decimals)))
        sl_limit = int(round(protect_limit_price(pos.side, "sl", sl_price) * (10 ** price_decimals)))
        logger.info(
            "Placing TP/SL %s mkt=%s tp_qty_int=%s sl_qty_int=%s lvl=%s px_dec=%s sz_dec=%s tp_trig=%s sl_trig=%s",
            pos.asset, pos.market_index, tp_size_int, sl_size_int, level, price_decimals, size_decimals, tp_trigger, sl_trigger,
        )
        tp_fns, sl_fns = self._protect_fns()
        if not pos.tp_client_index:
            pos.tp_client_index = int(time.time() * 1000) % 100_000_000
        if not pos.sl_client_index:
            pos.sl_client_index = (pos.tp_client_index + 7) % 100_000_000
        async with self._order_lock:
            try:
                last_tp_err = last_sl_err = None
                for fn in tp_fns:
                    if status["tp"] or tp_size_int <= 0:
                        break
                    result = await fn(
                        market_index=pos.market_index,
                        client_order_index=pos.tp_client_index,
                        base_amount=tp_size_int,
                        trigger_price=tp_trigger,
                        price=tp_limit if "limit" in getattr(fn, "__name__", "") else tp_trigger,
                        is_ask=is_ask,
                        reduce_only=True,
                    )
                    _, err = unpack_signer_result(result)
                    status["tp"] = err is None
                    if err:
                        last_tp_err = err
                        logger.warning("Exchange TP attach failed (%s): %s", getattr(fn, "__name__", fn), err)
                        if "invalid nonce" in str(err).lower():
                            await self._refresh_nonce()
                        pos.tp_client_index = (pos.tp_client_index + 11) % 100_000_000
                        await asyncio.sleep(0.25)
                await asyncio.sleep(0.3)
                for fn in sl_fns:
                    if status["sl"]:
                        break
                    result = await fn(
                        market_index=pos.market_index,
                        client_order_index=pos.sl_client_index,
                        base_amount=sl_size_int,
                        trigger_price=sl_trigger,
                        price=sl_limit if "limit" in getattr(fn, "__name__", "") else sl_trigger,
                        is_ask=is_ask,
                        reduce_only=True,
                    )
                    _, err = unpack_signer_result(result)
                    status["sl"] = err is None
                    if err:
                        last_sl_err = err
                        logger.warning("Exchange SL attach failed (%s): %s", getattr(fn, "__name__", fn), err)
                        if "invalid nonce" in str(err).lower():
                            await self._refresh_nonce()
                        pos.sl_client_index = (pos.sl_client_index + 11) % 100_000_000
                        await asyncio.sleep(0.25)
                if not status["tp"] and last_tp_err:
                    logger.warning("XRP-scale debug %s last TP err=%s trig=%s size=%s", pos.asset, last_tp_err, tp_trigger, size_int)
                pos.exchange_tp, pos.exchange_sl = status["tp"], status["sl"]
                pos.exchange_sl_price = sl_price if status["sl"] else pos.exchange_sl_price
            except Exception as e:
                logger.warning("Exchange TP/SL attach error: %s", e)
                status["detail"] = f"TP/SL error: {e}"
                return status
        verified = await self.verify_protective_exits(pos)
        status["tp"] = bool(verified.get("tp") or status["tp"])
        status["sl"] = bool(verified.get("sl") or status["sl"])
        status["on_book"] = bool(status["tp"] or status["sl"])
        pos.exchange_tp, pos.exchange_sl = status["tp"], status["sl"]
        if status["tp"] and status["sl"]:
            status["detail"] = "exchange TP/SL on book"
        elif status["tp"] or status["sl"]:
            status["detail"] = "partial exchange protect; local watchdog backup"
        else:
            status["detail"] = "TP/SL FAILED — watchdog only"
        return status

    async def arm_protective_exits(
        self,
        pos: ActivePosition,
        *,
        retries: Optional[int] = None,
        require_both: bool = True,
    ) -> Dict[str, Any]:
        """
        Always arm local TP/SL prices, then retry exchange attach until both are on book
        (or retries exhausted). Local watchdog remains armed either way.
        """
        self.ensure_exit_prices(pos)
        if pos.tp_price <= 0 or pos.sl_price <= 0:
            logger.error("REFUSING unprotected %s — could not compute TP/SL prices", pos.asset)
            return {"tp": False, "sl": False, "detail": "missing local TP/SL prices", "on_book": False}

        max_tries = int(retries if retries is not None else os.getenv("PROTECT_ATTACH_RETRIES", "5"))
        max_tries = max(1, max_tries)
        last: Dict[str, Any] = {"tp": False, "sl": False, "detail": "not attempted", "on_book": False}
        for attempt in range(max_tries):
            pos.last_protect_attempt = time.time()
            last = await self.place_protective_exits(pos, pos.tp_price, pos.sl_price)
            ok = bool(last.get("tp") and last.get("sl")) if require_both else bool(last.get("tp") or last.get("sl"))
            if ok:
                logger.info(
                    "🛡️ [TP/SL ARMED] %s attempt=%s tp=%s sl=%s @ tp=$%.4f sl=$%.4f",
                    pos.asset, attempt + 1, last.get("tp"), last.get("sl"), pos.tp_price, pos.sl_price,
                )
                return last
            logger.warning(
                "TP/SL incomplete for %s (attempt %s/%s): %s — retrying",
                pos.asset, attempt + 1, max_tries, last.get("detail"),
            )
            await asyncio.sleep(0.35 + 0.2 * attempt)
        logger.error(
            "🚨 [UNPROTECTED] %s still missing exchange TP/SL after %s tries — LOCAL WATCHDOG ACTIVE tp=$%.4f sl=$%.4f",
            pos.asset, max_tries, pos.tp_price, pos.sl_price,
        )
        last["detail"] = f"retries exhausted; local watchdog armed tp={pos.tp_price} sl={pos.sl_price}"
        return last

    @staticmethod
    def _close_if_unprotected_enabled() -> bool:
        return os.getenv("NEWS_CLOSE_IF_UNPROTECTED", "1").strip().lower() in {"1", "true", "yes", "on"}

    async def _close_if_unprotected(
        self,
        pos: ActivePosition,
        armed: Dict[str, Any],
        *,
        mark: Optional[float] = None,
    ) -> bool:
        """
        If exchange TP+SL could not be attached after retries, flatten the position
        (NEWS_CLOSE_IF_UNPROTECTED, default on). A news position that only has a local
        watchdog is unprotected across process restarts / WS drops; a missed catalyst
        costs far less than an unbounded loss. Returns True when the position was closed.
        """
        if bool(armed.get("tp")) and bool(armed.get("sl")):
            return False
        if not self._close_if_unprotected_enabled():
            return False
        if not self.is_live:
            return False
        price = float(mark or 0.0)
        if price <= 0:
            try:
                snap = await self.fetch_market_snapshot(pos.asset, pos.market_index)
                price = float(snap.price) if snap else 0.0
            except Exception as se:
                logger.warning("Unprotected-close price lookup failed for %s: %s", pos.asset, se)
        if price <= 0:
            price = float(pos.entry_price or 0.0)
        logger.error(
            "🚨 [UNPROTECTED→CLOSE] %s tp=%s sl=%s — flattening (NEWS_CLOSE_IF_UNPROTECTED=1)",
            pos.asset, armed.get("tp"), armed.get("sl"),
        )
        try:
            await self.cancel_open_orders(pos.market_index, [pos.tp_order_index, pos.sl_order_index])
            closed = await self.close_position(pos, price)
        except Exception as ce:
            logger.error("Unprotected-close failed for %s: %s — local watchdog remains armed", pos.asset, ce)
            return False
        if closed:
            pos.is_active = False
            self.active_positions.pop(pos.position_id, None)
        return bool(closed)

    async def enforce_exits_on_all_positions(self) -> Dict[str, int]:
        """Every tick: ensure every live position has TP+SL prices and exchange attaches."""
        summary = {"checked": 0, "armed": 0, "retried": 0, "missing_local": 0}
        now = time.time()
        min_gap = float(os.getenv("PROTECT_RETRY_SECONDS", "3.0"))
        for pos in list(self.active_positions.values()):
            if not pos.is_active:
                continue
            summary["checked"] += 1
            self.ensure_exit_prices(pos)
            if pos.tp_price <= 0 or pos.sl_price <= 0:
                summary["missing_local"] += 1
                continue
            if pos.exchange_tp and pos.exchange_sl:
                continue
            if now - float(pos.last_protect_attempt or 0.0) < min_gap:
                continue
            summary["retried"] += 1
            result = await self.arm_protective_exits(pos, retries=2, require_both=True)
            if result.get("tp") and result.get("sl"):
                summary["armed"] += 1
        return summary

    async def amend_trailing_sl(self, pos: ActivePosition) -> bool:
        if self.is_live and self.signer_client is None:
            await self._ensure_signer()
        if not self.signer_client or not pos.sl_price:
            pos.pending_sl_amend = False
            return False
        now = time.time()
        if now - pos.last_sl_amend_ts < 15:
            return False
        if pos.exchange_sl_price and pos.entry_price:
            moved = abs(pos.sl_price - pos.exchange_sl_price) / pos.entry_price
            if moved < 0.0008:
                pos.pending_sl_amend = False
                return False
        from trade_exits import protect_limit_price

        meta = self._meta(pos.asset)
        price_decimals = self._int_or(meta.get("price_decimals"), 2)
        size_decimals = self._int_or(meta.get("size_decimals"), 4)
        size_int = int(pos.size_eth * (10 ** size_decimals))
        sl_trigger = int(round(pos.sl_price * (10 ** price_decimals)))
        sl_limit = int(round(protect_limit_price(pos.side, "sl", pos.sl_price) * (10 ** price_decimals)))
        _, sl_fns = self._protect_fns()
        sl_fn = sl_fns[0] if sl_fns else None
        if not sl_fn or size_int <= 0:
            pos.pending_sl_amend = False
            return False
        async with self._order_lock:
            try:
                if pos.sl_order_index and hasattr(self.signer_client, "cancel_order"):
                    result = await self.signer_client.cancel_order(pos.market_index, pos.sl_order_index)
                    _, err = unpack_signer_result(result)
                    if err:
                        logger.warning("Trail SL cancel failed: %s", err)
                        if "invalid nonce" in str(err).lower():
                            await self._refresh_nonce()
                        return False
                    await asyncio.sleep(0.3)
                pos.sl_client_index = int(time.time() * 1000) % 100_000_000
                result = await sl_fn(
                    market_index=pos.market_index,
                    client_order_index=pos.sl_client_index,
                    base_amount=size_int,
                    trigger_price=sl_trigger,
                    price=sl_limit,
                    is_ask=(pos.side == "BUY/LONG"),
                    reduce_only=True,
                )
                _, err = unpack_signer_result(result)
                if err:
                    logger.warning("Trail SL replace failed: %s", err)
                    return False
            except Exception as e:
                logger.warning("Trail SL amend error: %s", e)
                return False
        pos.last_sl_amend_ts = now
        pos.exchange_sl_price = pos.sl_price
        pos.pending_sl_amend = False
        verified = await self.verify_protective_exits(pos, timeout=4.0)
        pos.exchange_sl = bool(verified.get("sl"))
        logger.info("Trail SL amended for %s -> %s on_book=%s", pos.asset, pos.sl_price, pos.exchange_sl)
        return True

    async def execute_trade(
        self,
        asset: str = "ETH",
        market_index: int = 0,
        is_ask: bool = False,
        current_market_price: float = 2650.0,
        custom_tp_pct: Optional[float] = None,
        reason: str = "MANUAL_ENTRY",
        notional_usd: Optional[float] = None,
        conviction: Optional[float] = None,
        margin_utilization_pct: Optional[float] = None,
        strategy_approved: bool = False,
        reservation_id: str = "",
        collateral_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Executes a sized trade and registers Take-Profit watchdog. Live is fail-closed.

        New opens must pass strategy approval (`strategy_approved=True`) unless
        REQUIRE_STRATEGY_GATE=0 (emergency only).

        SPEED_MODE: strategy-approved opens skip spread/VWAP HTTP and return on order ACK
        (fill confirm + protective exits run in background).
        """
        from trade_exits import policy_for, tp_sl_prices

        require_gate = os.getenv("REQUIRE_STRATEGY_GATE", "1").strip().lower() in {
            "1", "true", "yes", "on",
        }
        if require_gate and not strategy_approved:
            return {
                "success": False,
                "error": "strategy gate required — open via execute_strategy_entry / news risk approve",
            }

        existing = self.existing_position(asset, market_index)
        if existing:
            return {"success": False, "error": f"{asset} already has an open {existing.side} position"}

        # Opposing Whale Sweep Veto: block non-whale entries against fresh tape; whale-following trades skip.
        skip_whale_veto = (
            "whale" in (reason or "").lower()
            or os.getenv("WHALE_SKIP_OPPOSING_VETO", "1").strip().lower() in {"1", "true", "yes", "on"}
        )
        if not skip_whale_veto and hasattr(self, "_recent_whale_signals"):
            whale_info = self._recent_whale_signals.get(asset.upper())
            if whale_info:
                w_side, w_notional, w_ts = whale_info
                if (time.time() - w_ts) < 15.0:
                    trade_side = "SELL" if is_ask else "BUY"
                    opposing = (w_side in ["BUY", "LONG"] and trade_side == "SELL") or (w_side in ["SELL", "SHORT"] and trade_side == "BUY")
                    if opposing:
                        logger.warning("🐋 [WHALE VETO] Rejecting %s %s: opposing whale sweep ($%s) occurred %.1fs ago",
                                       trade_side, asset, f"{w_notional:,.0f}", time.time() - w_ts)
                        return {"success": False, "error": f"opposing whale sweep ({w_side} ${w_notional:,.0f}) within 15s"}

        # Prefer caller/cache collateral — never block fire path on fresh HTTP when strategy-sized
        if self.is_live and not os.getenv("WALLET_ADDRESS", "").strip():
            return {"success": False, "error": "live collateral query failed: WALLET_ADDRESS is not set"}
        if collateral_usd is None or float(collateral_usd) <= 0:
            collateral_usd = self.cached_collateral_usd()
        if collateral_usd is None or float(collateral_usd) <= 0:
            collateral_usd = await self.fetch_available_collateral_usd()
        if collateral_usd is None:
            return {"success": False, "error": "live collateral query failed"}

        if notional_usd is not None:
            capped_notional = min(float(notional_usd), float(os.getenv("NEWS_MAX_TRADE_USD", "250.0")))
            order_size = capped_notional / max(1e-6, current_market_price)
        else:
            order_size = self.calculate_max_order_size(
                collateral_usd,
                current_market_price,
                conviction=conviction,
                margin_utilization_pct=margin_utilization_pct,
                max_trade_usd=float(os.getenv("NEWS_MAX_TRADE_USD", "250.0")),
            )
        meta = self._meta(asset)
        min_base = float(meta.get("min_base_amount") or 0.0)
        if min_base and order_size < min_base:
            min_notional = min_base * current_market_price
            budget = float(notional_usd) if notional_usd is not None else float(os.getenv("NEWS_MAX_TRADE_USD", "25"))
            return {
                "success": False,
                "error": f"exchange min {min_base} {asset} is ${min_notional:.2f}, above risk budget ${budget:.2f}",
            }
        size_decimals = self._int_or(meta.get("size_decimals"), 4)
        order_size = round(order_size, size_decimals) if size_decimals > 0 else float(int(order_size))
        if order_size <= 0:
            return {"success": False, "error": "order size is zero"}
        if meta.get("market_index") not in (None, 0) or asset.upper() != "ETH":
            market_index = int(meta.get("market_index") or market_index)
        side_str = "SELL/SHORT" if is_ask else "BUY/LONG"
        policy = policy_for(asset, override_tp=custom_tp_pct, override_sl=self.default_sl_pct if custom_tp_pct else None)

        fast = self._speed_mode() and strategy_approved
        vwap_price = current_market_price
        expected_slippage_bps = 0.0

        if not (fast and self._skip_vwap_guard()):
            book = self.depth_engine.get_or_create_book(market_index, symbol=asset)
            need_depth = not (book.sorted_bid_prices or book.sorted_ask_prices)
            skip_spread = self._speed_mode() and os.getenv("SPEED_SKIP_SPREAD_CHECK", "1").strip().lower() in {
                "1", "true", "yes", "on"
            }
            if skip_spread and not need_depth:
                spread = float(getattr(book, "spread_bps", 0.0) or 0.0)
            elif need_depth and not skip_spread:
                book, spread = await asyncio.gather(
                    self.fetch_orderbook_depth(market_index),
                    self.fetch_spread_bps(market_index),
                )
            elif need_depth:
                book = await self.fetch_orderbook_depth(market_index)
                spread = float(getattr(book, "spread_bps", 0.0) or 0.0)
            else:
                spread = await self.fetch_spread_bps(market_index)
            if spread > policy.max_spread_bps:
                return {"success": False, "error": f"spread {spread:.1f} bps above {policy.max_spread_bps:.0f} bps exit cap"}

            if not book.sorted_bid_prices or not book.sorted_ask_prices:
                book = await self.fetch_orderbook_depth(market_index)

            max_slip_bps = getattr(policy, "max_slippage_bps", 50.0) if hasattr(policy, "max_slippage_bps") else 50.0
            requested_notional = float(notional_usd) if notional_usd is not None else (order_size * current_market_price)

            # Liquidity & Spread-Aware Fill Router:
            # Dynamically scale order size down by 50% if orderbook spread > 12 bps to prevent adverse fills
            if spread > 12.0:
                old_notional = requested_notional
                requested_notional = requested_notional * 0.50
                logger.info(
                    "💧 [SPREAD SIZING] Spread %.1f bps > 12 bps: scaling notional $%.2f -> $%.2f",
                    spread, old_notional, requested_notional
                )

            if book.sorted_ask_prices or book.sorted_bid_prices:
                adj_notional = liquidity_adjusted_size(
                    orderbook=book,
                    side="SELL" if is_ask else "BUY",
                    requested_usd=requested_notional,
                    max_slippage_bps=max_slip_bps,
                    fallback_price=current_market_price,
                )
                vwap_price, filled_usd, expected_slippage_bps, depth_exhausted = calculate_vwap(
                    orderbook=book,
                    side="SELL" if is_ask else "BUY",
                    target_notional_usd=adj_notional,
                    fallback_price=current_market_price,
                )
                if adj_notional < requested_notional:
                    order_size = adj_notional / max(1e-6, current_market_price)
                    order_size = round(order_size, size_decimals) if size_decimals > 0 else float(int(order_size))
                    logger.info(
                        f"⚠️ [VWAP SIZING] Adjusted size: ${requested_notional:.2f} -> ${adj_notional:.2f} "
                        f"(VWAP: ${vwap_price:.2f}, Slip: {expected_slippage_bps:.1f} bps, Cap: {max_slip_bps:.0f} bps)"
                    )

        if order_size <= 0:
            return {"success": False, "error": "liquidity adjusted order size is zero"}

        slippage_mult = (1.0 - self.slippage_tolerance_pct / 100.0) if is_ask else (1.0 + self.slippage_tolerance_pct / 100.0)
        exec_price = current_market_price * slippage_mult

        from trade_exits import dynamic_kelly_margin
        effective_margin = margin_utilization_pct if margin_utilization_pct is not None else (
            dynamic_kelly_margin(conviction) if conviction is not None else self.max_margin_utilization_pct
        )
        logger.info(
            f"🚀 [MAX-SIZE EXECUTION] {side_str} {order_size} {asset} (@ ~${current_market_price:.2f} | VWAP: ${vwap_price:.2f}) | "
            f"Margin: {effective_margin:.1f}% (${float(collateral_usd) * (effective_margin / 100.0):.2f}) | Reason: {reason}"
        )

        import uuid
        pos_id = f"pos_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        position = ActivePosition(
            position_id=pos_id,
            asset=asset,
            market_index=market_index,
            side=side_str,
            entry_price=current_market_price,
            size_eth=order_size,
            notional_usd=order_size * current_market_price,
            tp_pct=policy.tp_pct,
            sl_pct=policy.sl_pct,
            highest_price=current_market_price,
            lowest_price=current_market_price,
            ordered_size=order_size,
            original_size=order_size,
            max_hold_seconds=policy.max_hold_seconds,
            trail_arm_pct=policy.trail_arm_pct,
            trail_gap_pct=policy.trail_gap_pct,
        )

        if not self.signer_client:
            await self._ensure_signer()
        if not self.signer_client:
            return {"success": False, "error": "live signer unavailable — cannot place orders"}

        tx_hash, err = await self._submit_live_order(asset, market_index, order_size, exec_price, is_ask)
        if err:
            logger.error("❌ [EXEC] Order rejected: %s", err)
            return {"success": False, "error": str(err)}

        self.ensure_exit_prices(position)
        from trade_exits import tp_ladder_prices

        async def _confirm_and_protect() -> None:
            # Always keep local TP/SL armed immediately (watchdog can exit even before exchange attach)
            self.ensure_exit_prices(position)
            filled = await self.wait_for_exchange_position(asset, market_index)
            if filled:
                filled_size = float(filled.get("size") or 0.0)
                if filled_size <= 0:
                    filled_size = order_size
                position.size_eth = filled_size
                position.ordered_size = order_size
                position.original_size = filled_size
                position.entry_price = float(filled.get("entry_price") or current_market_price)
                position.notional_usd = position.size_eth * position.entry_price
                self.ensure_exit_prices(position)
            else:
                logger.error(
                    "❌ [EXEC] Fill not confirmed for %s — still arming TP/SL on ordered size",
                    asset,
                )
            try:
                armed = await self.arm_protective_exits(position, retries=int(os.getenv("PROTECT_ATTACH_RETRIES", "5")))
            except Exception as pe:
                logger.warning("Protective exits (async) failed for %s: %s", asset, pe)
                armed = {"tp": False, "sl": False}
            await self._close_if_unprotected(position, armed)

        if self._async_fill_confirm():
            position.entry_time = self.clock.remember(asset, position.entry_time)
            self.active_positions[pos_id] = position
            # Local TP/SL prices exist before the background task finishes exchange attach
            self.ensure_exit_prices(position)
            asyncio.create_task(_confirm_and_protect())
            logger.info(
                "⚡ [SPEED ACK] Order submitted tx=%s — TP=$%.4f SL=$%.4f armed locally; exchange attach async for %s",
                tx_hash, position.tp_price, position.sl_price, asset,
            )
            return {
                "success": True,
                "mode": "LIVE_MAINNET",
                "asset": asset,
                "tx_hash": str(tx_hash),
                "position_id": pos_id,
                "side": side_str,
                "size_eth": position.size_eth,
                "ordered_size": order_size,
                "entry_price": position.entry_price,
                "notional_usd": position.notional_usd,
                "tp_target_price": position.tp_price,
                "sl_price": position.sl_price,
                "tp_pct": policy.tp_pct,
                "sl_pct": policy.sl_pct,
                "tp_ladder": list(tp_ladder_prices(side_str, position.entry_price, policy)),
                "max_hold_seconds": policy.max_hold_seconds,
                "protect": "async_arming",
                "exchange_tp": False,
                "exchange_sl": False,
                "on_book": None,
                "reason": reason,
                "speed_ack": True,
            }

        filled = await self.wait_for_exchange_position(asset, market_index)
        if not filled:
            logger.error("❌ [EXEC] Order sent but no exchange position for %s", asset)
            return {"success": False, "error": "order submitted but fill not confirmed on exchange", "tx_hash": str(tx_hash)}

        filled_size = float(filled.get("size") or 0.0)
        if filled_size <= 0:
            filled_size = order_size
        if filled_size + 1e-12 < order_size:
            logger.warning("Partial fill %s: filled=%s ordered=%s — TP/SL sized to fill", asset, filled_size, order_size)
        position.size_eth = filled_size
        position.ordered_size = order_size
        position.original_size = filled_size
        position.entry_price = float(filled.get("entry_price") or current_market_price)
        position.notional_usd = position.size_eth * position.entry_price
        self.ensure_exit_prices(position)
        tp_price, sl_price = position.tp_price, position.sl_price
        protect = await self.arm_protective_exits(position)
        position.entry_time = self.clock.remember(asset, position.entry_time)
        if await self._close_if_unprotected(position, protect, mark=current_market_price):
            return {"success": False, "error": "closed: protective exits could not be attached", "asset": asset}
        from trade_exits import already_through_exit, infer_tp_hits, scaled_out_qty
        mark = current_market_price
        itm = already_through_exit(side_str, mark, tp_price, sl_price)
        hits = infer_tp_hits(side_str, position.entry_price, mark, policy)
        self.active_positions[pos_id] = position
        if itm == "STOP_LOSS":
            logger.info("Fill already through STOP_LOSS on %s @ %s — closing now", asset, mark)
            await self.cancel_open_orders(position.market_index, [position.tp_order_index, position.sl_order_index])
            closed = await self.close_position(position, mark)
            position.is_active = bool(not closed)
            protect["detail"] = "closed immediately (STOP_LOSS)"
            protect["itm"] = itm
        elif hits >= 1:
            qty = scaled_out_qty(position.original_size, position.size_eth, hits)
            logger.info("Fill already through TP%s on %s @ %s — scaling out qty=%s", hits, asset, mark, qty)
            await self.cancel_open_orders(position.market_index, [position.tp_order_index, position.sl_order_index])
            closed = await self.close_position(position, mark, qty=(None if hits >= 4 else qty))
            if hits >= 4:
                position.is_active = bool(not closed)
                protect["detail"] = "closed immediately (TP4)"
            elif closed:
                position.tp_hits = hits
                position.sl_price = position.entry_price
                self.ensure_exit_prices(position)
                protect = await self.arm_protective_exits(position, retries=3)
                protect["detail"] = f"scaled out TP1-{hits}; runner SL@BE"
            protect["itm"] = f"PARTIAL_TP_{hits}"
        logger.info("✅ [LIVE FILL CONFIRMED] TxHash: %s size=%s ordered=%s entry=%s protect=%s", tx_hash, position.size_eth, order_size, position.entry_price, protect.get("detail"))
        return {
            "success": True,
            "mode": "LIVE_MAINNET",
            "asset": asset,
            "tx_hash": str(tx_hash),
            "position_id": pos_id,
            "side": side_str,
            "size_eth": position.size_eth,
            "ordered_size": order_size,
            "entry_price": position.entry_price,
            "notional_usd": position.notional_usd,
            "tp_target_price": position.tp_price,
            "sl_price": position.sl_price,
            "tp_pct": policy.tp_pct,
            "sl_pct": policy.sl_pct,
            "tp_ladder": list(tp_ladder_prices(side_str, position.entry_price, policy)),
            "max_hold_seconds": policy.max_hold_seconds,
            "protect": protect.get("detail"),
            "exchange_tp": protect.get("tp"),
            "exchange_sl": protect.get("sl"),
            "on_book": protect.get("on_book"),
            "reason": reason,
        }

    async def cancel_open_orders(self, market_index: int, extra_indexes: Optional[List[int]] = None) -> int:
        """Cancel leftover TP/SL (and any other) working orders for one market."""
        if self.is_live and self.signer_client is None:
            await self._ensure_signer()
        if not self.signer_client or market_index in (None, -1):
            return 0
        cancelled = 0
        async with self._order_lock:
            try:
                if hasattr(self.signer_client, "cancel_all_orders"):
                    tif = getattr(self.signer_client, "CANCEL_ALL_TIF_IMMEDIATE", 0)
                    result = await self.signer_client.cancel_all_orders(
                        time_in_force=tif,
                        timestamp_ms=0,
                        cancel_all_market_index=int(market_index),
                    )
                    _, err = unpack_signer_result(result)
                    if err:
                        logger.warning("cancel_all_orders market %s failed: %s", market_index, err)
                    else:
                        cancelled += 1
                for idx in extra_indexes or []:
                    if not idx or not hasattr(self.signer_client, "cancel_order"):
                        continue
                    result = await self.signer_client.cancel_order(int(market_index), int(idx))
                    _, err = unpack_signer_result(result)
                    if err is None:
                        cancelled += 1
                    elif err:
                        logger.debug("cancel_order %s/%s: %s", market_index, idx, err)
            except Exception as e:
                logger.warning("cancel open orders error: %s", e)
        return cancelled

    async def cancel_one_order(self, market_index: int, order_index: int) -> bool:
        if self.is_live and self.signer_client is None:
            await self._ensure_signer()
        if not self.signer_client or not order_index:
            return False
        async with self._order_lock:
            try:
                result = await self.signer_client.cancel_order(int(market_index), int(order_index))
                _, err = unpack_signer_result(result)
                if err:
                    logger.warning("cancel_order %s/%s failed: %s", market_index, order_index, err)
                    if "invalid nonce" in str(err).lower():
                        await self._refresh_nonce()
                    return False
                return True
            except Exception as e:
                logger.warning("cancel_one_order error: %s", e)
                return False

    async def sync_position_orders(self, pos: ActivePosition, open_count: int) -> Dict[str, Any]:
        """Every live position gets local TP/SL plus exactly one exchange TP and one SL when the book allows."""
        if self.is_live and self.signer_client is None:
            await self._ensure_signer()
        self.ensure_exit_prices(pos)
        if open_count == 2:
            pos.exchange_tp = pos.exchange_sl = True
            return {"tp": True, "sl": True, "detail": "book already has TP+SL", "pruned": 0}
        if open_count > 0:
            logger.info("Rebuilding TP/SL on %s (had %s working orders)", pos.asset, open_count)
            await self.cancel_open_orders(pos.market_index, [pos.tp_order_index, pos.sl_order_index])
            pos.exchange_tp = pos.exchange_sl = False
            pos.tp_client_index = pos.sl_client_index = 0
            pos.tp_order_index = pos.sl_order_index = 0
            await asyncio.sleep(0.35)
        else:
            logger.info("Attaching missing TP/SL on %s (0 working orders)", pos.asset)
        protect = await self.arm_protective_exits(pos, retries=3)
        protect["pruned"] = open_count if open_count > 2 else 0
        return protect

    async def care_open_orders(self, prices: Optional[Dict[str, float]] = None) -> Dict[str, int]:
        """Always own the book: cancel orphans/stale/unfilled extras, one TP/SL per live position."""
        from trade_exits import classify_working_order, policy_for, tp_sl_prices

        summary = {"cancelled": 0, "orphans": 0, "stale": 0, "attached": 0, "flattened": 0, "pruned": 0}
        if self.signer_client is None:
            await self._ensure_signer()
        if not self.signer_client:
            return summary
        now = time.time()
        if now - self._last_care_ts < 15:
            return summary
        self._last_care_ts = now
        prices = prices or {}
        live_positions = await self.fetch_account_positions()
        live_markets = {int(item["market_index"]) for item in live_positions if float(item.get("size") or 0) > 0 and item.get("market_index") is not None}
        live_symbols = {str(item.get("symbol") or "").upper() for item in live_positions if float(item.get("size") or 0) > 0 and item.get("symbol")}
        orders = await self.fetch_open_orders()
        flatten_assets: Dict[str, int] = {}
        for item in orders:
            market = self._order_int(item, "market_id", "market_index")
            symbol = str(item.get("symbol") or item.get("market_symbol") or "").upper()
            local = self.existing_position(symbol, market if market not in (0, -1) else None)
            max_age = local.max_hold_seconds if local else float(os.getenv("NEWS_ORDER_TTL_SECONDS", str(45 * 60)))
            entry_ttl = float(os.getenv("NEWS_ENTRY_TTL_SECONDS", "90"))
            kind = classify_working_order(item, live_markets, live_symbols, now, max_age, entry_ttl_seconds=entry_ttl)
            if kind == "keep":
                continue
            order_idx = self._order_int(item, "order_index", "order_id", "index")
            ok = False
            if order_idx:
                ok = await self.cancel_one_order(market, order_idx)
            if not ok and market not in (None, -1):
                await self.cancel_open_orders(market, [order_idx])
                ok = True
            if not ok:
                continue
            summary["cancelled"] += 1
            if kind == "orphan":
                summary["orphans"] += 1
                logger.info("Cancelled orphan/unfilled order market=%s idx=%s %s", market, order_idx, symbol)
            else:
                summary["stale"] += 1
                logger.info("Cancelled %s order market=%s idx=%s %s (news/entry expired)", kind, market, order_idx, symbol)
                if symbol:
                    flatten_assets[symbol] = market
                elif local:
                    flatten_assets[local.asset] = local.market_index
        for symbol, market in flatten_assets.items():
            pos = self.existing_position(symbol, market if market not in (0, -1) else None)
            mark = prices.get((pos.asset if pos else symbol).upper()) or (pos.entry_price if pos else 0.0)
            if pos and pos.is_active:
                if await self.close_position(pos, mark or pos.entry_price):
                    pos.is_active = False
                    summary["flattened"] += 1
            elif symbol in live_symbols:
                live = self.match_exchange_position(live_positions, symbol, market)
                if live:
                    dummy = ActivePosition(
                        position_id=f"stale_{symbol}",
                        asset=symbol,
                        market_index=int(live.get("market_index") or market),
                        side=live.get("side") or "BUY/LONG",
                        entry_price=float(live.get("entry_price") or mark or 0),
                        size_eth=float(live.get("size") or 0),
                        notional_usd=0.0,
                    )
                    if await self.close_position(dummy, mark or dummy.entry_price):
                        summary["flattened"] += 1
        live_positions = await self.fetch_account_positions()
        for live in live_positions:
            symbol = str(live.get("symbol") or "").upper()
            mkt_idx = int(live.get("market_index") or 0)
            size = float(live.get("size") or 0)
            if not symbol or size <= 0:
                continue
            pos = self.existing_position(symbol, mkt_idx)
            if pos is None:
                policy = policy_for(symbol)
                entry = float(live.get("entry_price") or 0)
                side = live.get("side") or "BUY/LONG"
                pos = ActivePosition(
                    position_id=f"adopted_{symbol}_{mkt_idx}",
                    asset=symbol,
                    market_index=mkt_idx,
                    side=side,
                    entry_price=entry,
                    size_eth=size,
                    notional_usd=size * entry,
                    tp_pct=policy.tp_pct or self.default_tp_pct or 2.5,
                    sl_pct=policy.sl_pct or 1.5,
                    is_active=True,
                )
                self.ensure_exit_prices(pos)
                self.active_positions[pos.position_id] = pos
                logger.info("🛡️ [CARE AUTO-ADOPT] %s %s Size=%s @ $%.4f", symbol, side, size, entry)
            self.ensure_exit_prices(pos)
            open_n = int(live.get("open_order_count") or live.get("position_tied_order_count") or 0)
            if open_n == 2:
                pos.exchange_tp = pos.exchange_sl = True
                continue
            # Unprotected positions: retry every few seconds; fully armed: longer gap
            gap = 3.0 if not (pos.exchange_tp and pos.exchange_sl) else 20.0
            if now - pos.last_protect_attempt < gap:
                continue
            pos.last_protect_attempt = now
            result = await self.sync_position_orders(pos, open_n)
            pruned = int(result.get("pruned") or 0)
            if pruned:
                summary["pruned"] += pruned
                summary["cancelled"] += max(0, pruned - 2)
            if result.get("tp") or result.get("sl"):
                summary["attached"] += 1
        return summary

    async def close_position(self, pos: ActivePosition, current_market_price: float, qty: Optional[float] = None) -> bool:
        """Close full size, or `qty` for a scale-out. Partials keep the clock and remaining TP/SL."""
        if self.is_live and self.signer_client is None:
            await self._ensure_signer()
        partial = qty is not None and qty > 0
        if not self.signer_client:
            logger.error("Close aborted %s: live signer unavailable", pos.position_id)
            return False
        books = await self.fetch_account_positions()
        live = self.match_exchange_position(books, pos.asset, pos.market_index)
        if live is None or float(live.get("size") or 0) <= 0:
            if not books:
                logger.error("Close aborted %s: account book unavailable (not assuming flat)", pos.asset)
                return False
            await self.cancel_open_orders(pos.market_index, [pos.tp_order_index, pos.sl_order_index])
            self.clock.forget(pos.asset)
            return True
        live_size = float(live.get("size") or pos.size_eth)
        size = min(float(qty), live_size) if partial else live_size
        if size <= 0:
            return True
        market_index = int(live.get("market_index") or pos.market_index)
        target_left = max(0.0, live_size - size) if partial else 0.0
        for attempt in range(3):
            _, err = await self._submit_live_order(
                pos.asset,
                market_index,
                size,
                current_market_price,
                is_ask=(pos.side == "BUY/LONG"),
                reduce_only=True,
            )
            if err:
                logger.error("❌ [EXEC] Close error for %s: %s", pos.position_id, err)
                await asyncio.sleep(0.6)
                continue
            deadline = time.time() + 12.0
            while time.time() < deadline:
                still = await self.wait_for_exchange_position(pos.asset, pos.market_index, timeout=1.5)
                left = float(still.get("size") or 0) if still else 0.0
                if left <= target_left + 1e-9:
                    await self.cancel_open_orders(market_index, [pos.tp_order_index, pos.sl_order_index])
                    if left <= 1e-12:
                        self.clock.forget(pos.asset)
                    else:
                        pos.size_eth = left
                    return True
                await asyncio.sleep(0.5)
        logger.error("Close not confirmed flat for %s", pos.position_id)
        return False

    async def execute_catalyst_snipe(self, signal: CatalystSignal, current_market_price: float) -> Dict[str, Any]:
        """News catalyst entry — must go through strategy gate (no raw execute_trade)."""
        is_ask = (signal.sentiment == "BEARISH")
        budget = min(float(os.getenv("NEWS_MAX_TRADE_USD", "100.0")), float(os.getenv("NEWS_REQUESTED_USD", "75.0")))
        # Prefer bot-level strategy entry when available via bound sniper bot
        bot = getattr(self, "_strategy_bot", None)
        if bot is not None and hasattr(bot, "execute_strategy_entry"):
            return await bot.execute_strategy_entry(
                asset=signal.target_asset,
                market_index=signal.market_index,
                is_ask=is_ask,
                price=current_market_price,
                notional_usd=budget,
                reason=f"NEWS: {signal.headline[:40]}",
                entry_mode="news",
            )
        # Maker-checker: never self-approve. Without the bound strategy bot
        # (which owns the risk gate) there is no approval path, so refuse.
        logger.error("REFUSING catalyst entry for %s — no strategy bot bound", signal.target_asset)
        return {"success": False, "error": "no strategy bot bound — catalyst entry refused without risk approval"}

    async def close_all_positions(self, current_market_price: Any = 2650.0) -> int:
        """Emergency flatten using each asset's own mark. Confirms flat on live."""
        closed_count = 0
        price_map: Dict[str, float] = current_market_price if isinstance(current_market_price, dict) else {}
        fallback = 0.0 if isinstance(current_market_price, dict) else float(current_market_price or 0)
        for pos in list(self.active_positions.values()):
            if not pos.is_active:
                continue
            mark = price_map.get(pos.asset.upper()) or (fallback if fallback > 0 else pos.entry_price)
            ok = await self.close_position(pos, mark)
            if ok:
                pos.is_active = False
                closed_count += 1
                await self.cancel_open_orders(pos.market_index, [pos.tp_order_index, pos.sl_order_index])
            else:
                logger.error("Flatten not confirmed for %s", pos.position_id)
        return closed_count

    async def harvest_exchange_exits(self, prices: Dict[str, float]) -> List[Dict[str, Any]]:
        """If Lighter TP/SL already flattened a position, book the exit and cancel leftover orders."""
        closed: List[Dict[str, Any]] = []
        live_positions = await self.fetch_account_positions()
        for pos in list(self.active_positions.values()):
            if not pos.is_active:
                continue
            still = self.match_exchange_position(live_positions, pos.asset, pos.market_index)
            if still is not None and float(still.get("size") or 0) > 0:
                live_size = float(still.get("size") or 0)
                if live_size + 1e-9 < (pos.size_eth or 0) * 0.98:
                    dropped = max(0.0, pos.size_eth - live_size)
                    mark = prices.get(pos.asset.upper()) or pos.entry_price
                    if pos.side == "BUY/LONG":
                        pnl_pct = ((mark - pos.entry_price) / pos.entry_price) * 100.0 if pos.entry_price else 0.0
                        pnl_usd = (mark - pos.entry_price) * dropped
                    else:
                        pnl_pct = ((pos.entry_price - mark) / pos.entry_price) * 100.0 if pos.entry_price else 0.0
                        pnl_usd = (pos.entry_price - mark) * dropped
                    pos.original_size = pos.original_size or (pos.size_eth or live_size)
                    pos.size_eth = live_size
                    pos.tp_hits = min(4, int(pos.tp_hits or 0) + 1)
                    if pos.tp_hits >= 1:
                        pos.sl_price = pos.entry_price
                    self.ensure_exit_prices(pos)
                    pos.exchange_tp = pos.exchange_sl = False
                    closed.append({
                        "type": "EXCHANGE_PARTIAL",
                        "pos_id": pos.position_id,
                        "asset": pos.asset,
                        "pnl_pct": pnl_pct,
                        "pnl_usd": pnl_usd,
                        "exit_price": mark,
                        "close_qty": dropped,
                        "full": False,
                        "already_done": True,
                        "tp_level": pos.tp_hits,
                    })
                    logger.info("Exchange scaled out %s leftover=%s tp_hits=%s", pos.asset, live_size, pos.tp_hits)
                continue
            mark = prices.get(pos.asset.upper()) or pos.entry_price
            if pos.side == "BUY/LONG":
                pnl_pct = ((mark - pos.entry_price) / pos.entry_price) * 100.0 if pos.entry_price else 0.0
                pnl_usd = (mark - pos.entry_price) * pos.size_eth
            else:
                pnl_pct = ((pos.entry_price - mark) / pos.entry_price) * 100.0 if pos.entry_price else 0.0
                pnl_usd = (pos.entry_price - mark) * pos.size_eth
            await self.cancel_open_orders(pos.market_index, [pos.tp_order_index, pos.sl_order_index])
            self.clock.forget(pos.asset)
            pos.is_active = False
            closed.append({
                "type": "EXCHANGE_EXIT",
                "pos_id": pos.position_id,
                "asset": pos.asset,
                "pnl_pct": pnl_pct,
                "pnl_usd": pnl_usd,
                "exit_price": mark,
            })
            logger.info("Exchange already flat %s %s pnl=$%.4f — leftover orders cancelled", pos.asset, pos.side, pnl_usd)
        return closed

    async def check_take_profit_and_stop_loss(self, prices: Dict[str, float]) -> List[Dict[str, Any]]:
        """Watchdog checking if active positions hit TP or Stop-Loss using per-asset prices."""
        closed_events = []
        now = time.time()
        for pos_id, pos in list(self.active_positions.items()):
            if not pos.is_active:
                continue
            self.ensure_exit_prices(pos)
            current_price = prices.get(pos.asset.upper())
            if current_price is None or current_price <= 0 or pos.entry_price <= 0:
                logger.debug("TP watchdog skip %s: no mark (entry=%s)", pos.asset, pos.entry_price)
                continue
            from trade_exits import already_through_exit
            itm = already_through_exit(pos.side, current_price, pos.tp_price, pos.sl_price)
            if itm == "STOP_LOSS":
                closed_events.append(self._exit_event(pos, "STOP_LOSS", current_price, pos.size_eth, full=True))
                continue
            if itm == "TAKE_PROFIT":
                closed_events.extend(self._scale_out_events(pos, current_price))
                continue
            if abs(current_price - pos.entry_price) / pos.entry_price > 0.20 and (now - pos.entry_time) < 15:
                logger.warning(
                    "Skipping TP/SL for %s: mark %s vs entry %s looks like a cross-asset price",
                    pos.asset, current_price, pos.entry_price,
                )
                continue

            pos.highest_price = max(pos.highest_price, current_price)
            pos.lowest_price = min(pos.lowest_price, current_price)

            # Dynamic Breakeven Acceleration: tighten to BE faster if volatility normalizes quickly
            engine = getattr(self, "volatility_engine", None)
            if engine and pos.tp_hits == 0 and pos.entry_price > 0:
                is_long = pos.side.startswith("BUY")
                pnl_now = ((current_price - pos.entry_price) / pos.entry_price * 100.0) if is_long else ((pos.entry_price - current_price) / pos.entry_price * 100.0)
                if engine.should_accelerate_breakeven(pos.asset, pos.side, pos.entry_price, current_price, pnl_now):
                    from trade_exits import breakeven_sl
                    be_price = breakeven_sl(pos.side, pos.entry_price, 0.1)
                    if is_long and (pos.sl_price <= 0 or be_price > pos.sl_price):
                        pos.sl_price = be_price
                        pos.pending_sl_amend = True
                        logger.info("⚡ [BE-ACCELERATION] Volatility normalized for %s: accelerated SL to BE @ %s", pos.asset, be_price)
                    elif not is_long and (pos.sl_price <= 0 or be_price < pos.sl_price):
                        pos.sl_price = be_price
                        pos.pending_sl_amend = True
                        logger.info("⚡ [BE-ACCELERATION] Volatility normalized for %s: accelerated SL to BE @ %s", pos.asset, be_price)

            from trade_exits import ExitPolicy, trail_stop
            policy = ExitPolicy(pos.tp_pct, pos.sl_pct, pos.trail_arm_pct, pos.trail_gap_pct, pos.max_hold_seconds, 80)
            prev_sl = pos.sl_price
            if pos.sl_price:
                pos.sl_price = trail_stop(pos.side, pos.entry_price, pos.highest_price, pos.lowest_price, pos.sl_price, policy)
            else:
                from trade_exits import tp_sl_prices
                _, pos.sl_price = tp_sl_prices(pos.side, pos.entry_price, policy)
            if pos.sl_price and prev_sl and abs(pos.sl_price - prev_sl) / max(pos.entry_price, 1e-9) >= 0.0008:
                pos.pending_sl_amend = True

            if pos.side == "BUY/LONG":
                pnl_pct = ((current_price - pos.entry_price) / pos.entry_price) * 100.0
                realized_usd = (current_price - pos.entry_price) * pos.size_eth
                sl_hit = current_price <= pos.sl_price
                tp_hit = pos.tp_price > 0 and current_price >= pos.tp_price
            else:
                pnl_pct = ((pos.entry_price - current_price) / pos.entry_price) * 100.0
                realized_usd = (pos.entry_price - current_price) * pos.size_eth
                sl_hit = current_price >= pos.sl_price
                tp_hit = pos.tp_price > 0 and current_price <= pos.tp_price

            hit = None
            if tp_hit:
                closed_events.extend(self._scale_out_events(pos, current_price))
                continue
            if sl_hit or pnl_pct <= -pos.sl_pct:
                hit = "STOP_LOSS"
            elif now - pos.entry_time >= pos.max_hold_seconds:
                hit = "TIME_STOP"
            if not hit:
                continue
            closed_events.append(self._exit_event(pos, hit, current_price, pos.size_eth, full=True))

        return closed_events

    def _exit_event(self, pos: ActivePosition, kind: str, price: float, qty: float, full: bool) -> Dict[str, Any]:
        if pos.side == "BUY/LONG":
            pnl_pct = ((price - pos.entry_price) / pos.entry_price) * 100.0 if pos.entry_price else 0.0
            pnl_usd = (price - pos.entry_price) * qty
        else:
            pnl_pct = ((pos.entry_price - price) / pos.entry_price) * 100.0 if pos.entry_price else 0.0
            pnl_usd = (pos.entry_price - price) * qty
        return {
            "type": kind,
            "pos_id": pos.position_id,
            "asset": pos.asset,
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "exit_price": price,
            "close_qty": qty,
            "full": full,
        }

    def _partial_tp_event(self, pos: ActivePosition, price: float) -> Dict[str, Any]:
        events = self._scale_out_events(pos, price)
        return events[0] if events else self._exit_event(pos, "PARTIAL_TP_1", price, pos.size_eth, full=True)

    def _scale_out_events(self, pos: ActivePosition, price: float) -> List[Dict[str, Any]]:
        """Emit every TP level cleared (TP1..TP4). TP1 also moves SL to BE+0.1%."""
        from trade_exits import TP_LADDER_LEVELS, already_through_exit, breakeven_sl, partial_qty, policy_for, scale_tp_price

        events: List[Dict[str, Any]] = []
        remaining = pos.size_eth
        hits = int(pos.tp_hits or 0)
        orig = pos.original_size or pos.size_eth
        mult = getattr(pos, "atr_multiplier", 1.0) or 1.0
        policy = policy_for(pos.asset, override_tp=pos.tp_pct or None, override_sl=pos.sl_pct or None, atr_multiplier=mult)
        while hits < TP_LADDER_LEVELS and remaining > 0:
            nxt = hits + 1
            tp_px = scale_tp_price(pos.side, pos.entry_price, policy, nxt, atr_multiplier=mult)
            if already_through_exit(pos.side, price, tp_px, 0.0) != "TAKE_PROFIT":
                break
            qty = partial_qty(orig, remaining, nxt)
            if qty <= 0:
                break
            full = nxt >= TP_LADDER_LEVELS
            ev = self._exit_event(pos, f"PARTIAL_TP_{nxt}", price, qty, full=full)
            ev["tp_level"] = nxt
            events.append(ev)
            remaining -= qty
            hits = nxt
            if nxt == 1:
                pos.sl_price = breakeven_sl(pos.side, pos.entry_price, 0.1)
                pos.pending_sl_amend = True
            elif nxt >= 2:
                pos.trail_gap_pct = policy.trail_gap_pct
                pos.pending_sl_amend = True
        return events


# =============================================================================
# NEWS INGESTION STREAMS
# =============================================================================

def _synthetic_normalized_event(
    *,
    event_id: str,
    source_id: str,
    publisher: str,
    headline: str,
    body: str,
    entities,
    event_type: str,
    direction: str,
    confidence: float,
    source_score: float = 0.90,
    category: str = "wire",
    cluster_id: str = "",
    url: str = "",
    guid: str = "",
    materiality: float = 0.85,
) -> NormalizedNewsEvent:
    now = datetime.now(timezone.utc)
    gid = guid or event_id
    return NormalizedNewsEvent(
        event_id=event_id,
        source_id=source_id,
        publisher=publisher,
        headline=headline,
        body=body,
        url=url,
        guid=gid,
        published_at=now,
        ingested_at=now,
        source_score=source_score,
        category=category,
        content_hash=gid,
        entities=tuple(entities),
        event_type=event_type,
        direction=direction,
        materiality=materiality,
        confidence=confidence,
        cluster_id=cluster_id or event_id,
        raw={"adapter": "whale_radar", "source_id": source_id},
    )


class NewsIngestionManager:
    """Polls breaking crypto feeds in background with sub-15ms TreeNews WebSocket streaming."""

    def __init__(self, on_news_callback: Callable[[NewsItem], Any], db_path: Optional[str] = None):
        self.on_news_callback = on_news_callback
        self.is_running = False
        self.registry = NewsSourceRegistry()
        self.pipeline = NewsPipeline(db_path=db_path, min_sources=int(os.getenv("NEWS_MIN_SOURCES", "1")))
        self.scheduler = NewsSourceScheduler(
            self.registry,
            self._handle_records,
            db_path=db_path,
            max_concurrency=int(os.getenv("NEWS_FETCH_CONCURRENCY", "24")),
        )
        self.treenews_ws = TreeNewsWebSocketClient(on_records=self._handle_records)
        try:
            from x_monitor import XPostMonitorTool
            self.x_monitor = XPostMonitorTool(on_records=self._handle_records)
        except Exception as _xe:
            logger.warning("Could not initialize XPostMonitor: %s", _xe)
            self.x_monitor = None
        try:
            from hyperliquid_whale_tracker import HyperliquidWhaleTracker
            self.whale_tracker = HyperliquidWhaleTracker(on_whale_signal=self._handle_whale_signal)
        except Exception:
            self.whale_tracker = None
        try:
            from cross_dex_arbitrage import CrossDexArbitrageEngine
            self.cross_dex_arb = CrossDexArbitrageEngine(on_opportunity=self._handle_arb_opportunity)
        except Exception:
            self.cross_dex_arb = None

    async def start(self):
        self.is_running = True
        enabled = [source.source_id for source in self.registry.enabled() if source.adapter != "webhook"]
        logger.info("📡 [NEWS] Multi-source news registry listening: %s", ", ".join(enabled))
        asyncio.create_task(self.scheduler.run_forever())
        if os.getenv("TREENEWS_WS_ENABLED", "true").lower() == "true":
            self.treenews_ws.start()
            logger.info("⚡ [NEWS] TreeNews Sub-15ms WebSocket Ingestion Client streaming active")
        if self.whale_tracker and os.getenv("HL_WHALES_ENABLED", "true").lower() == "true":
            await self.whale_tracker.start()
            logger.info("🐋 [NEWS] Hyperliquid Smart Money & Whale Scanner active (Tape + Leaderboard)")
        if self.cross_dex_arb and os.getenv("CROSS_DEX_ARB_ENABLED", "true").lower() == "true":
            await self.cross_dex_arb.start()
            logger.info("⚡ [ARB] Cross-DEX Hyperliquid Price-Lag Arbitrage Engine active (25 bps lead detector)")
        if self.x_monitor and os.getenv("X_MONITOR_ENABLED", "true").lower() == "true":
            asyncio.create_task(self.x_monitor.run_monitor_loop())
            logger.info("🐦 [X-RADAR] X (Twitter) Post Monitor Tool active (treg.x.user.posts / tikhub)")

    async def stop(self):
        self.is_running = False
        await self.scheduler.stop()
        await self.treenews_ws.stop()
        if self.whale_tracker:
            await self.whale_tracker.stop()
        if self.cross_dex_arb:
            await self.cross_dex_arb.stop()
        if self.x_monitor:
            self.x_monitor.is_running = False

    async def _handle_arb_opportunity(self, opp: Any):
        """Cross-DEX price-lag arbitrage signal handler."""
        if not getattr(opp, "is_actionable", False):
            return
        asset = str(opp.asset).upper()
        dir_val = getattr(opp.direction, "value", str(opp.direction))
        is_buy = dir_val.startswith("BUY")
        side = "BUY" if is_buy else "SELL"
        direction = "BULLISH" if is_buy else "BEARISH"
        
        arb_event = _synthetic_normalized_event(
            event_id=f"arb_{asset}_{int(time.time()*1000)}",
            source_id="cross_dex_arbitrage",
            publisher="HyperliquidLeadArb",
            headline=f"⚡ Hyperliquid Leads zkLighter: {asset} {side} (+{opp.spread_bps:.1f} bps)",
            body=f"Price-lag arbitrage: HL=${opp.hl_price:,.2f} vs zkL=${opp.zklighter_mid:,.2f} (Net Edge: {opp.net_edge_bps:.1f} bps)",
            entities=(asset,),
            event_type="arbitrage",
            direction=direction,
            confidence=0.92,
            source_score=0.92,
            category="wire",
            cluster_id=f"arb_{asset}_{direction}_{int(time.time()*1000)}",
        )
        item = NewsItem(
            source="CrossDexArbitrage",
            headline=arb_event.headline,
            body=arb_event.body,
            timestamp=time.time(),
            url="",
        )
        await self.on_news_callback(item, arb_event)

    async def _handle_whale_signal(self, sig: Dict[str, Any]):
        """Whale radar auto-execution when smart-money fills large orders."""
        asset = str(sig.get("asset", "")).upper()
        side = str(sig.get("side", "")).upper()
        notional = float(sig.get("notional_usd", 0.0))
        price = float(sig.get("entry_price", 0.0))
        trader = str(sig.get("trader", "Whale Leader"))

        logger.info(
            "🐋 [WHALE RADAR] %s | %s %s ($%s USD) @ $%s",
            asset,
            side,
            trader,
            f"{notional:,.0f}",
            f"{price:,.2f}",
        )

        # Maintain rolling whale sweep records for opposing-trade veto
        if not hasattr(self, "_recent_whale_signals"):
            self._recent_whale_signals: Dict[str, Tuple[str, float, float]] = {}  # asset -> (side, notional, timestamp)
        self._recent_whale_signals[asset] = (side, notional, time.time())
        exec_engine = getattr(self, "_executor", None)
        if exec_engine is not None:
            if not hasattr(exec_engine, "_recent_whale_signals"):
                exec_engine._recent_whale_signals = {}
            exec_engine._recent_whale_signals[asset] = (side, notional, time.time())

        # Trigger auto-entry when smart money notional >= $35,000 USD (Upgrade: Hyperliquid Whale Co-Pilot)
        min_whale_usd = float(os.getenv("WHALE_MIN_TRADE_USD", "35000"))
        if notional >= min_whale_usd and asset in ["BTC", "ETH", "SOL", "HYPE", "TRUMP", "DOGE", "AVAX"]:
            direction = "BULLISH" if side in ["BUY", "LONG"] else "BEARISH"
            now_ms = int(time.time() * 1000)
            whale_event = _synthetic_normalized_event(
                event_id=f"whale_{asset}_{now_ms}",
                source_id="hyperliquid_whale",
                publisher="HyperliquidTape",
                headline=f"🐋 Hyperliquid Mega Whale {side} ${notional:,.0f} {asset}",
                body=f"Smart money position entry on Hyperliquid tape at ${price:,.2f}",
                entities=(asset,),
                event_type="whale",
                direction=direction,
                confidence=0.88,
                source_score=0.88,
                category="wire",
                cluster_id=f"whale_{asset}_{direction}_{now_ms}",
            )
            item = NewsItem(
                source="HyperliquidWhale",
                headline=whale_event.headline,
                body=whale_event.body,
                timestamp=time.time(),
                url="",
            )
            await self.on_news_callback(item, whale_event)

    async def _handle_records(self, records):
        for event in self.pipeline.process(records):
            published_at = event.published_at.timestamp() if event.published_at else event.ingested_at.timestamp()
            item = NewsItem(
                source=event.publisher,
                headline=event.headline,
                body=event.body,
                timestamp=published_at,
                url=event.url,
            )
            await self.on_news_callback(item, event)

    async def handle_records(self, records):
        """Public ingest path for Poke / webhook injectors."""
        await self._handle_records(records)

    async def _poll_crypto_rss(self):
        await self.scheduler.run_forever()


# =============================================================================
# ORCHESTRATOR & CLI ENTRYPOINT
# =============================================================================

class LighterNewsSniperBot:
    """Master Orchestrator for Catalyst and Manual Trading."""

    def __init__(self, is_live: bool = True, max_margin_pct: float = 85.0):
        # Always request live; kill switch can still block via live_execution_allowed.
        self.is_live = live_execution_allowed(True)
        self.classifier = CatalystClassifier()
        self.executor = MaxSizeExecutionEngine(
            is_live=self.is_live,
            max_margin_utilization_pct=max_margin_pct,
            default_tp_pct=2.5,
            default_sl_pct=1.5,
        )
        self.executor._strategy_bot = self
        self.db_path = os.getenv("NEWS_DB_PATH", str(Path(__file__).with_name("lighter_news.db")))
        self.news_manager = NewsIngestionManager(self._handle_news_event, db_path=self.db_path)
        self.news_manager._executor = self.executor
        self.markets = MarketRegistry()
        self.tickers = TickerCache()
        self.intent_queue = TradeIntentQueue(self.db_path)
        self.positions = PositionBook(self.db_path)
        self.metrics = NewsMetrics()
        self.audit = AuditLog(str(Path(__file__).with_name("news_audit.jsonl")))
        self.current_market_price = float(os.getenv("LIGHTER_ETH_PRICE", "2650.0"))
        self.current_market_timestamp = time.time()
        self.story_fingerprint_window_sec = float(os.getenv("NEWS_STORY_FINGERPRINT_WINDOW_SEC", "900.0"))
        self._story_fingerprints: List[Tuple[str, str, str, set, float]] = []
        self.news_risk_gate = LighterNewsRiskGate(live=True)
        self.momentum_filter = CrossExchangeMomentumFilter()
        self.news_risk_gate.momentum_filter = self.momentum_filter
        self._latest_news_events: Dict[str, NormalizedNewsEvent] = {}
        self.kill_file = Path(__file__).with_name("NEWS_KILL_SWITCH")
        self._kill_action_latched = False
        self._kill_flatten_in_flight = False
        self.reconciled = False
        from news_scoreboard import ShadowScoreboard
        self.scoreboard = ShadowScoreboard(self.db_path)
        self.ledger = TradeLedger(self.db_path)
        self.news_manager.pipeline.on_correction = self._on_correction

        try:
            from master_profit_orchestrator import MasterProfitOrchestrator
            self.orchestrator = MasterProfitOrchestrator()
            logger.info("🏛️ [MasterProfitOrchestrator] Armed with ALL 125+ institutional quant strategies.")
        except Exception as oe:
            self.orchestrator = None
            logger.warning(f"MasterProfitOrchestrator init warning: {oe}")

        try:
            from lighter_telegram import LighterTelegramBot
            from lighter_db import LighterDBManager
            self.db = LighterDBManager()
            self.recent_news = []
            self.tg_bot = LighterTelegramBot(
                bot_context={
                    "market_index": 0,
                    "db": self.db,
                    "executor": self.executor,
                    "news_manager": self.news_manager,
                    "bot_instance": self,
                    "bot": self,
                    "orchestrator": self.orchestrator,
                    "master_orchestrator": self.orchestrator,
                    "intent_queue": self.intent_queue,
                    "positions": self.positions,
                    "metrics": self.metrics,
                    "markets": self.markets,
                    "ledger": self.ledger,
                }
            )
        except Exception as tge:
            logger.warning(f"Telegram listener init warning: {tge}")

    def _prune_story_fingerprints(self, now: float) -> None:
        cutoff = now - self.story_fingerprint_window_sec
        self._story_fingerprints = [item for item in self._story_fingerprints if item[4] >= cutoff]

    def _extract_story_tokens(self, text: str) -> set:
        words = set(re.findall(r"[a-z0-9]+", text.lower()))
        stopwords = {
            "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
            "and", "or", "as", "is", "are", "was", "were", "it", "this", "that", "be", "has", "have"
        }
        return words - stopwords

    def _is_duplicate_story_fingerprint(self, asset: str, side: str, event: NormalizedNewsEvent, now: float) -> bool:
        if getattr(event, "event_type", "") in {"whale", "arbitrage", "momentum"} or (event.source_id or "").startswith(("hyperliquid", "whale", "cross_dex")):
            return False
        sym = asset.upper()
        cluster_id = getattr(event, "cluster_id", "")
        tokens = self._extract_story_tokens(f"{event.headline} {event.body}")
        for cached_asset, cached_side, cached_cluster, cached_tokens, ts in self._story_fingerprints:
            if cached_asset == sym:
                if cluster_id and cached_cluster and cluster_id == cached_cluster:
                    return True
                if cached_side == side:
                    union = tokens | cached_tokens
                    jaccard = len(tokens & cached_tokens) / len(union) if union else 1.0
                    if jaccard >= 0.35 or len(tokens & cached_tokens) >= 3:
                        return True
        return False

    def _record_story_fingerprint(self, asset: str, side: str, event: NormalizedNewsEvent, now: float) -> None:
        sym = asset.upper()
        cluster_id = getattr(event, "cluster_id", "")
        tokens = self._extract_story_tokens(f"{event.headline} {event.body}")
        self._story_fingerprints.append((sym, side, cluster_id, tokens, now))

    def _on_correction(self, event: NormalizedNewsEvent) -> None:
        self.metrics.inc("corrections")
        self.audit.emit("correction", event.event_id, cluster_id=event.cluster_id, headline=event.headline)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.intent_queue.invalidate_cluster(event.cluster_id))
        except RuntimeError:
            pass

    def _authorized(self) -> bool:
        chat_id = (os.getenv("ADMIN_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        return bool(chat_id) and chat_id != "0"

    def kill_engaged(self) -> bool:
        return self.kill_file.exists() or os.getenv("NEWS_KILL_SWITCH", "").lower() in {"1", "true", "yes"}

    def set_kill(self, on: bool) -> None:
        if on:
            self.kill_file.write_text("1", encoding="utf-8")
            try:
                from email_notifier import email_send_kill_alert
                email_send_kill_alert("manual/API kill switch")
            except Exception:
                pass
        elif self.kill_file.exists():
            self.kill_file.unlink()
            self._kill_action_latched = False

    def mode_label(self) -> str:
        if self.kill_engaged():
            return "KILLED"
        return "LIVE"

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
        """
        Canonical new-position path: risk gate (in-memory caps) → execute_trade.
        SPEED_MODE: no snapshot/spread HTTP — uses caller price + cached collateral.
        """
        symbol = (asset or "").upper()
        side = "SELL/SHORT" if is_ask else "BUY/LONG"
        if self.kill_engaged():
            await self.enforce_kill_cancel_flatten()
            return {"success": False, "error": "kill switch engaged"}

        from lighter_news_risk import MarketSnapshot

        speed = self.executor._speed_mode()
        snap_price = float(price or 0)
        # Prefer in-memory ticker — never wait on HTTP before fire in SPEED_MODE
        if not speed or snap_price <= 0:
            cached = self.tickers.get(symbol) if hasattr(self, "tickers") else None
            if cached and float(getattr(cached, "price", 0) or 0) > 0:
                snap_price = float(cached.price)
                snapshot = cached
                snapshot.timestamp = time.time()
            else:
                snapshot = await self.executor.fetch_market_snapshot(symbol, market_index)
                if snapshot and float(getattr(snapshot, "price", 0) or 0) > 0:
                    snap_price = float(snapshot.price)
                    snapshot.timestamp = time.time()
                else:
                    snapshot = MarketSnapshot(
                        asset=symbol,
                        price=snap_price,
                        timestamp=time.time(),
                        market_index=int(market_index),
                    )
        else:
            cached = self.tickers.get(symbol) if hasattr(self, "tickers") else None
            if cached and float(getattr(cached, "price", 0) or 0) > 0:
                snap_price = float(cached.price)
                snapshot = cached
                snapshot.timestamp = time.time()
            else:
                snapshot = MarketSnapshot(
                    asset=symbol,
                    price=snap_price,
                    timestamp=time.time(),
                    market_index=int(market_index),
                )

        if not speed and float(getattr(snapshot, "spread_bps", 0) or 0) <= 0:
            try:
                spread = await self.executor.fetch_spread_bps(int(snapshot.market_index or market_index))
                if spread > 0:
                    snapshot.spread_bps = spread
            except Exception:
                pass

        collateral = self.executor.cached_collateral_usd()
        if collateral is None:
            collateral = await self.executor.fetch_available_collateral_usd()
        base_requested = float(notional_usd) if notional_usd is not None else float(
            os.getenv("NEWS_REQUESTED_USD", "200.0")
        )
        if notional_usd is None and collateral and collateral > 0:
            compounding_pct = float(os.getenv("NEWS_COMPOUNDING_PCT", "20.0"))
            max_conviction_usd = float(os.getenv("NEWS_MAX_HIGH_CONVICTION_USD", "250.0"))
            compounded = round(collateral * (compounding_pct / 100.0), 2)
            base_requested = max(base_requested, min(max_conviction_usd, compounded))
        requested_usd = min(self.news_risk_gate.max_trade_usd, base_requested)

        decision = await self.news_risk_gate.approve(
            None,
            snapshot,
            requested_usd,
            confirmed=True,
            authorized=self._authorized(),
            asset=symbol,
            side=side,
            collateral_usd=collateral,
            stop_distance_pct=stop_distance_pct,
            active_positions=self.executor.active_positions,
            entry_mode=entry_mode,
        )
        if not decision.approved:
            logger.warning("Strategy entry vetoed for %s: %s", symbol, "; ".join(decision.reasons))
            return {
                "success": False,
                "error": "; ".join(decision.reasons) or "strategy gate rejected",
                "reasons": list(decision.reasons),
                "sized_usd": decision.sized_usd,
            }

        try:
            result = await self.executor.execute_trade(
                asset=symbol,
                market_index=int(snapshot.market_index or market_index),
                is_ask=is_ask,
                current_market_price=float(snapshot.price or snap_price),
                custom_tp_pct=custom_tp_pct,
                reason=reason,
                notional_usd=decision.sized_usd or requested_usd,
                strategy_approved=True,
                reservation_id=decision.reservation_id,
                collateral_usd=collateral,
            )
            if result.get("success"):
                self.news_risk_gate.record_fill(symbol)
            return result
        finally:
            await self.news_risk_gate.release(decision.reservation_id, symbol, side)

    def _kill_flatten_wanted(self) -> bool:
        raw = os.getenv("KILL_FLATTEN")
        if raw is None or str(raw).strip() == "":
            return True
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    async def enforce_kill_cancel_flatten(self) -> bool:
        """
        When NEWS_KILL_SWITCH engages mid-run: cancel-all working orders,
        optionally flatten open positions (KILL_FLATTEN, default true).
        Returns True while kill remains engaged.
        """
        if not self.kill_engaged():
            self._kill_action_latched = False
            return False
        if self._kill_flatten_in_flight:
            return True

        do_flatten = self._kill_flatten_wanted()
        # After first engage, only re-run flatten if inventory still open.
        if self._kill_action_latched:
            if not do_flatten:
                return True
            try:
                live = await self.executor.fetch_account_positions()
            except Exception:
                return True
            still_open = [i for i in live if float(i.get("size") or 0) > 0]
            if not still_open and not any(p.is_active for p in self.executor.active_positions.values()):
                return True

        self._kill_flatten_in_flight = True
        try:
            logger.critical(
                "[KILL] NEWS_KILL_SWITCH engaged — cancel_all + flatten=%s (latched=%s)",
                do_flatten,
                self._kill_action_latched,
            )
            markets: set = set()
            for pos in list(self.executor.active_positions.values()):
                if pos.market_index not in (None, -1):
                    markets.add(int(pos.market_index))
            try:
                live = await self.executor.fetch_account_positions()
            except Exception as e:
                logger.warning("[KILL] position fetch failed: %s", e)
                live = []
            for item in live:
                mid = item.get("market_index")
                if mid not in (None, -1):
                    markets.add(int(mid))
            try:
                orders = await self.executor.fetch_open_orders()
                for item in orders:
                    mid = self.executor._order_int(item, "market_id", "market_index")
                    if mid not in (None, -1):
                        markets.add(int(mid))
            except Exception as e:
                logger.debug("[KILL] open-order scan: %s", e)

            for market in markets:
                try:
                    await self.executor.cancel_open_orders(int(market))
                except Exception as e:
                    logger.error("[KILL] cancel_all market=%s failed: %s", market, e)

            if do_flatten:
                prices: Dict[str, float] = {}
                for pos in list(self.executor.active_positions.values()):
                    snap = self.tickers.get(pos.asset) if hasattr(self, "tickers") else None
                    if snap and getattr(snap, "price", 0) > 0:
                        prices[pos.asset.upper()] = float(snap.price)
                try:
                    closed = await self.executor.close_all_positions(prices or self.current_market_price)
                    logger.critical("[KILL] Flattened %s tracked position(s)", closed)
                except Exception as e:
                    logger.error("[KILL] close_all_positions failed: %s", e)
                try:
                    live = await self.executor.fetch_account_positions()
                except Exception:
                    live = []
                for item in live:
                    symbol = str(item.get("symbol") or "").upper()
                    size = float(item.get("size") or 0)
                    if not symbol or size <= 0:
                        continue
                    mark = prices.get(symbol) or float(item.get("entry_price") or 0) or self.current_market_price
                    dummy = ActivePosition(
                        position_id=f"kill_{symbol}",
                        asset=symbol,
                        market_index=int(item.get("market_index") or 0),
                        side=item.get("side") or "BUY/LONG",
                        entry_price=float(item.get("entry_price") or mark or 0),
                        size_eth=size,
                        notional_usd=size * float(mark or 1),
                    )
                    try:
                        await self.executor.cancel_open_orders(dummy.market_index)
                        ok = await self.executor.close_position(dummy, mark)
                        logger.critical("[KILL] Exchange flatten %s ok=%s", symbol, ok)
                    except Exception as e:
                        logger.error("[KILL] Exchange flatten %s failed: %s", symbol, e)

            self._kill_action_latched = True
            try:
                from email_notifier import email_send_kill_alert
                email_send_kill_alert("auto flatten engaged")
            except Exception:
                pass
        finally:
            self._kill_flatten_in_flight = False
        return True

    @property
    def markets_by_symbol(self) -> MarketRegistry:
        return self.markets

    async def on_incoming_news(self, records):
        """Poke / injector path: same as NewsIngestionManager.handle_records."""
        await self.news_manager.handle_records(records)

    async def handle_normalized_event(self, event: NormalizedNewsEvent):
        published_at = event.published_at.timestamp() if event.published_at else event.ingested_at.timestamp()
        item = NewsItem(
            source=event.publisher,
            headline=event.headline,
            body=event.body,
            timestamp=published_at,
            url=event.url or "",
        )
        await self._handle_news_event(item, event)

    async def _handle_news_event(self, news: NewsItem, event: Optional[NormalizedNewsEvent] = None):
        if event is None:
            return
        if not hasattr(self, "recent_news"):
            self.recent_news = []
        self.recent_news.append(event)
        if len(self.recent_news) > 50:
            self.recent_news.pop(0)

        # News ingestion runs silently in background. Telegram alerts only on executed trades.
        if os.getenv("TELEGRAM_NEWS_BROADCAST", "false").lower() in ("true", "1", "yes") and event.confidence >= 0.95:
            emoji = "🟢" if event.direction == "BULLISH" else ("🔴" if event.direction == "BEARISH" else "⚪")
            try:
                from lighter_telegram import tg_send
                tg_send(
                    f"📡 <b>BREAKING NEWS RADAR</b> (<i>{event.source_id.upper()}</i>)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{emoji} <b>{event.direction}</b> | Conviction: <code>{int(event.confidence * 100)}%</code>\n"
                    f"📰 <b>{event.headline}</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
            except Exception:
                pass

        self.metrics.inc("ingested")
        self.audit.emit("observed", event.event_id, source=event.source_id, type=event.event_type, headline=event.headline)

        # Speed mode: only live-eligible fast wires reach sizing/risk gate (skip stale RSS/X backlog).
        if self.executor._speed_mode() and event.event_type not in {"whale", "arbitrage", "momentum"}:
            eligible, reason = self.news_risk_gate.source_is_live_eligible(event)
            if not eligible:
                self.metrics.inc("shadow_only" if "shadow only" in reason else "stale_feed")
                return

        from news_quality import quality_veto

        ok, veto_reason = quality_veto(event)
        if not ok:
            self.metrics.inc("quality_veto")
            logger.info("Quality veto: %s | %s", veto_reason, event.headline[:120])
            return
        confirmed = self.news_manager.pipeline.confirmed(event)
        from news_direction import macro_routes
        market = None
        side = "BUY/LONG"
        for symbol, route_side in macro_routes(event):
            found = self.markets.get(symbol)
            if found:
                market = found
                side = route_side
                break
        if market is None:
            market, reason = self.markets.resolve(event)
            side = "SELL/SHORT" if event.direction == "BEARISH" else "BUY/LONG"
        if market is None:
            self.metrics.inc("unresolved_asset")
            return
        confirmed_only = os.getenv("NEWS_AUTO_TRADE_CONFIRMED_ONLY", "false").lower() == "true"
        if confirmed_only and not confirmed and event.confidence < 0.80 and event.event_type not in {"whale", "arbitrage", "momentum"}:
            self.metrics.inc("unconfirmed")
            return

        # Check active position lockout
        if self.executor.existing_position(market.symbol, market.market_index):
            self.metrics.inc("active_position_lockout")
            logger.info("[DEDUP] Dropped duplicate news: Active position already exists for %s", market.symbol)
            return

        # Story Fingerprint / Cluster Lockout: Track traded clusters and story fingerprints with a 15-minute expiration
        now = time.time()
        self._prune_story_fingerprints(now)
        if self._is_duplicate_story_fingerprint(market.symbol, side, event, now):
            self.metrics.inc("duplicate_catalyst_lockout")
            logger.info("[DEDUP] Dropped duplicate news: Story fingerprint/cluster already processed for %s (%s)", market.symbol, event.headline[:80])
            return

        snapshot = self.tickers.get(market.symbol)
        if snapshot is None or not snapshot.fresh or snapshot.price <= 0:
            fetched = await self.executor.fetch_market_snapshot(market.symbol, market.market_index)
            if fetched and fetched.price > 0:
                fetched.timestamp = time.time()
                snapshot = fetched
                self.tickers.update(fetched)
        if snapshot is None or snapshot.price <= 0:
            # Direct depth book mid-price fallback
            depth_book = await self.executor.fetch_orderbook_depth(market.market_index)
            if depth_book and depth_book.mid_price > 0:
                snapshot = MarketSnapshot(
                    asset=market.symbol,
                    price=depth_book.mid_price,
                    spread_bps=depth_book.spread_bps,
                    timestamp=time.time(),
                    market_index=market.market_index,
                )
                self.tickers.update(snapshot)
            else:
                fallback_snapshot = self.tickers.snapshot_or_env(market)
                if fallback_snapshot and fallback_snapshot.price > 0:
                    fallback_snapshot.timestamp = time.time()
                    snapshot = fallback_snapshot
                    self.tickers.update(snapshot)
                else:
                    # Final fallback to last known price in tickers
                    last_known = self.tickers.get(market.symbol)
                    if last_known and last_known.price > 0:
                        last_known.timestamp = time.time()
                        snapshot = last_known
                    else:
                        self.metrics.inc("stale_price_veto")
                        logger.warning("News signal vetoed: live market price is missing or stale for %s", market.symbol)
                        return
        if snapshot:
            snapshot.timestamp = time.time()
        # Prefer snapshot/book spread; only hit HTTP if missing or SPEED_SKIP_SPREAD_CHECK off
        skip_spread_http = self.executor._speed_mode() and os.getenv(
            "SPEED_SKIP_SPREAD_CHECK", "1"
        ).strip().lower() in {"1", "true", "yes", "on"}
        if skip_spread_http and snapshot and float(getattr(snapshot, "spread_bps", 0) or 0) > 0:
            spread = float(snapshot.spread_bps)
        else:
            spread = await self.executor.fetch_spread_bps(int(snapshot.market_index or market.market_index))
            if spread > 0 and snapshot:
                snapshot.spread_bps = spread

        if side not in market.enabled_sides:
            self.metrics.inc("side_disabled")
            logger.warning("News signal vetoed: side %s not in enabled_sides for %s (enabled: %s)", side, market.symbol, market.enabled_sides)
            return

        base_requested = float(os.getenv("NEWS_REQUESTED_USD", "200.0"))
        max_conviction_usd = float(os.getenv("NEWS_MAX_HIGH_CONVICTION_USD", "250.0"))
        
        # 📈 Dynamic Collateral Compounding Engine (Compound 20% of total collateral per trade)
        collateral = await self.executor.fetch_available_collateral_usd()
        if collateral and collateral > 0:
            compounding_pct = float(os.getenv("NEWS_COMPOUNDING_PCT", "20.0"))  # 20% of margin per trade
            compounded_base = round(collateral * (compounding_pct / 100.0), 2)
            base_requested = max(base_requested, min(max_conviction_usd, compounded_base))
            logger.info("📈 [AUTO-COMPOUNDING] Sizing dynamically set to $%.2f (Collateral: $%.2f, Rate: %.1f%%)", base_requested, collateral, compounding_pct)

        # Scale trade size dynamically above base for highest conviction breaking news
        if event and event.confidence and event.confidence >= 0.85:
            # 85% -> base ($200), 95%+ -> max_conviction_usd ($250)
            scale_factor = 1.0 + ((event.confidence - 0.85) / 0.15) * ((max_conviction_usd / max(1.0, base_requested)) - 1.0)
            scaled_usd = round(min(max_conviction_usd, base_requested * scale_factor), 2)
            requested_usd = min(self.news_risk_gate.max_trade_usd, scaled_usd)
            logger.info("🔥 [HIGH CONVICTION NEWS] Scaled sizing for %s from $%.2f to $%.2f (Conviction: %.1f%%)", market.symbol, base_requested, requested_usd, event.confidence * 100.0)
        else:
            requested_usd = min(self.news_risk_gate.max_trade_usd, base_requested)

        # ⚡ Microstructure L2 Order Book Imbalance Sizing Booster (+25% to +50% on heavy orderbook pressure)
        try:
            depth_book = getattr(self.executor, "depth_book", None)
            if depth_book and hasattr(depth_book, "calculate_order_book_imbalance"):
                obi = depth_book.calculate_order_book_imbalance(depth=5)
                # If buying and bids heavily outweigh asks (OBI > +0.30) OR selling and asks outweigh bids (OBI < -0.30)
                if (side.startswith("BUY") and obi >= 0.30) or (side.startswith("SELL") and obi <= -0.30):
                    obi_boost = min(1.5, 1.0 + abs(obi) * 0.5)
                    requested_usd = round(min(max_conviction_usd, requested_usd * obi_boost), 2)
                    logger.info("⚡ [L2 IMBALANCE BOOST] Order book imbalance %.2f boosted sizing for %s to $%.2f", obi, market.symbol, requested_usd)
        except Exception as e:
            logger.debug("L2 Imbalance check skipped: %s", e)

        authorized = self._authorized()
        # Reuse cached collateral from compounding step (TTL cache) — do not double-fetch
        momentum_confirmed = None
        skip_momentum = (
            self.executor._speed_mode()
            and os.getenv("SPEED_SKIP_MOMENTUM", "1").strip().lower() in {"1", "true", "yes", "on"}
        )
        if (
            not skip_momentum
            and self.momentum_filter
            and event.confidence >= self.momentum_filter.high_conviction_threshold
        ):
            sentiment = "BULLISH" if side.startswith("BUY") else "BEARISH"
            m_conf = await self.momentum_filter.verify_spike(market.symbol, sentiment, conviction_score=event.confidence)
            if m_conf.confirmed:
                momentum_confirmed = True
                self.metrics.inc("momentum_confirmed")
                logger.info("⚡ Cross-Exchange Momentum confirmed on Binance/Bybit: %s", m_conf.summary)
            else:
                self.metrics.inc("momentum_unconfirmed")
                # Non-blocking: Step down to baseline sizing instead of hard-blocking early trades
                requested_usd = min(requested_usd, base_requested)
                logger.warning("⚠️ Cross-Exchange Momentum unconfirmed: %s (Executing with baseline sizing $%.2f)", m_conf.summary, requested_usd)
                momentum_confirmed = True if not getattr(self.momentum_filter, "require_confirmation", False) else None
        elif skip_momentum:
            momentum_confirmed = True
            self.metrics.inc("momentum_skipped_speed")

        # Refresh snapshot timestamp right before risk gate approval to eliminate any network latency jitter
        if snapshot:
            snapshot.timestamp = time.time()

        decision = await self.news_risk_gate.approve(
            event,
            snapshot,
            requested_usd,
            confirmed,
            authorized,
            asset=market.symbol,
            side=side,
            collateral_usd=collateral,
            stop_distance_pct=market.sl_pct,
            momentum_confirmed=momentum_confirmed,
            active_positions=self.executor.active_positions,
        )
        if not decision.approved:
            self.metrics.inc("vetoed")
            self.audit.emit("vetoed", event.event_id, reasons=decision.reasons)
            logger.warning("News signal vetoed: %s", "; ".join(decision.reasons))
            logger.info("🚫 [1st-News Guard] Duplicate/cooldown signal dropped silently: %s", "; ".join(decision.reasons))
            if any("shadow only" in reason for reason in decision.reasons):
                # Source not live-eligible (e.g. polled RSS): still measure it so the
                # allowlist can be widened on evidence rather than guesswork.
                try:
                    from news_scoreboard import ShadowBet
                    self.scoreboard.record(ShadowBet(
                        bet_id=event.event_id + "_shadow", asset=market.symbol, side=side,
                        event_type=event.event_type, headline=event.headline,
                        entry_price=float(snapshot.price), created_at=time.time(),
                        cluster_id=event.cluster_id,
                    ))
                    self.metrics.inc("shadow_only")
                except Exception as se:
                    logger.debug("shadow bet record failed for %s: %s", event.event_id, se)
            return

        if self.kill_engaged():
            await self.enforce_kill_cancel_flatten()
            await self.news_risk_gate.release(decision.reservation_id, market.symbol, side)
            self.metrics.inc("killed")
            return

        intent = await self.intent_queue.enqueue(event, market, side, decision.sized_usd or requested_usd)
        if intent.status != "intent" or intent.event_id != event.event_id:
            self.metrics.inc("duplicate_intent")
            logger.info(
                "🚫 [INTENT DEDUP] Dropped %s %s (%s): intent status=%s event_id=%s",
                side, market.symbol, event.event_type, intent.status, intent.event_id,
            )
            await self.news_risk_gate.release(decision.reservation_id, market.symbol, side)
            return
        await self.intent_queue.mark(intent.intent_id, "reserved", reservation_id=decision.reservation_id)
        self._record_story_fingerprint(market.symbol, side, event, now)

        try:
            result = await self.executor.execute_trade(
                asset=market.symbol,
                market_index=int(snapshot.market_index or market.market_index),
                is_ask=side.startswith("SELL"),
                current_market_price=snapshot.price,
                reason=f"NEWS: {event.headline[:40]}",
                notional_usd=decision.sized_usd or requested_usd,
                strategy_approved=True,
                reservation_id=decision.reservation_id,
                collateral_usd=collateral,
            )
            if not result.get("success"):
                err = str(result.get("error", "execution failed"))
                await self.intent_queue.mark(intent.intent_id, "rejected", reasons=(err,))
                self.metrics.inc("rejected")
                logger.warning(
                    "❌ [EXEC REJECT] %s %s (%s): %s",
                    side, market.symbol, event.event_type, err,
                )
                return
            intent.fill_price = float(result.get("entry_price") or snapshot.price)
            intent.fill_size = float(result.get("size_eth") or 0.0)
            await self.intent_queue.mark(intent.intent_id, "filled", reservation_id=decision.reservation_id)
            self.positions.activate_from_fill(intent)
            self.news_risk_gate.record_fill(market.symbol)
            self.metrics.inc("filled_live")
            try:
                filled_at = time.time()
                self.ledger.record_entry(
                    trade_id=event.event_id,
                    position_id=str(result.get("position_id") or intent.intent_id),
                    asset=market.symbol,
                    side=side,
                    source_id=event.source_id,
                    publisher=event.publisher,
                    event_type=event.event_type,
                    catalyst_headline=event.headline,
                    confidence=event.confidence,
                    published_at=event.published_at.timestamp() if event.published_at else None,
                    ingested_at=event.ingested_at.timestamp(),
                    decided_at=now,
                    filled_at=filled_at,
                    entry_price=float(result.get("entry_price") or snapshot.price),
                    signal_price=float(snapshot.price),
                    size=float(result.get("size_eth") or 0.0),
                    notional_usd=float(result.get("notional_usd") or 0.0),
                    taker_fee_bps=float(os.getenv("LIGHTER_TAKER_FEE_BPS", "0")),
                )
            except Exception as ledger_err:
                logger.debug("Trade ledger entry failed: %s", ledger_err)

            # Attach catalyst headline & type directly to executor active position
            active_exec_pos = self.executor.existing_position(market.symbol, int(snapshot.market_index or market.market_index))
            if active_exec_pos:
                active_exec_pos.catalyst_headline = event.headline
                active_exec_pos.catalyst_type = getattr(event, "event_type", "")
                self.executor.ensure_exit_prices(active_exec_pos)
                result["tp_pct"] = active_exec_pos.tp_pct
                result["sl_pct"] = active_exec_pos.sl_pct
                result["tp_target_price"] = active_exec_pos.tp_price
                result["sl_price"] = active_exec_pos.sl_price
            from news_scoreboard import ShadowBet
            self.scoreboard.record(ShadowBet(
                bet_id=event.event_id + "_live", asset=market.symbol, side=side, event_type=event.event_type,
                headline=event.headline, entry_price=float(result.get("entry_price") or snapshot.price),
                created_at=time.time(), cluster_id=event.cluster_id,
            ))
            self.audit.emit("filled", event.event_id, mode=result.get("mode"), asset=market.symbol, side=side, notional=result.get("notional_usd"))
            try:
                from lighter_telegram import format_fill_card, tg_send
                card = format_fill_card(result, headline=event.headline)
                if self.executor._speed_mode():
                    asyncio.get_running_loop().run_in_executor(None, tg_send, card)
                else:
                    tg_send(card)
            except Exception as tge:
                logger.warning("Telegram alert error: %s", tge)
            try:
                from email_notifier import email_send_trade_alert
                email_send_trade_alert(
                    asset=market.symbol,
                    side=side,
                    price=float(result.get("entry_price") or snapshot.price),
                    notional_usd=float(result.get("notional_usd") or 0.0),
                    tp_price=result.get("tp_target_price"),
                    sl_price=result.get("sl_price"),
                    reason=f"{event.event_type}: {event.headline[:80]}",
                )
            except Exception as eme:
                logger.warning("Email alert error: %s", eme)
        finally:
            await self.news_risk_gate.release(decision.reservation_id, market.symbol, side)

    async def _price_loop(self):
        while True:
            try:
                books = await self.executor.fetch_order_catalog()
                self.markets.ingest_catalog(books)
                markets = list(self.markets.enabled())
                semaphore = asyncio.Semaphore(20)

                async def refresh(market):
                    async with semaphore:
                        return await self.executor.fetch_market_snapshot(market.symbol, market.market_index)

                snapshots = await asyncio.gather(*(refresh(market) for market in markets), return_exceptions=True)
                for market, snapshot in zip(markets, snapshots):
                    if isinstance(snapshot, Exception) or snapshot is None or snapshot.price <= 0:
                        continue
                    self.tickers.update(snapshot)
                    if hasattr(self.executor, "volatility_engine") and self.executor.volatility_engine:
                        self.executor.volatility_engine.on_tick(snapshot.asset, snapshot.price, timestamp=snapshot.timestamp)
                    if snapshot.asset == "ETH":
                        self.current_market_price = snapshot.price
                        self.current_market_timestamp = snapshot.timestamp
            except Exception as e:
                logger.debug("[Price loop] %s", e)
            await asyncio.sleep(2.0)

    async def _honor_close_requests(self, prices: Dict[str, float]) -> None:
        """Flatten symbols listed in CLOSE_SYMBOLS. Keep the file until exchange is flat."""
        path = Path(__file__).with_name("CLOSE_SYMBOLS")
        wanted: set[str] = {item.strip().upper() for item in os.getenv("NEWS_CLOSE_SYMBOLS", "").split(",") if item.strip()}
        if path.exists():
            try:
                wanted |= {
                    line.strip().upper()
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")
                }
            except OSError as exc:
                logger.warning("CLOSE_SYMBOLS read failed: %s", exc)
        if not wanted:
            return
        leftover = set(wanted)
        live = await self.executor.fetch_account_positions()
        live_by_sym = {str(item.get("symbol") or "").upper(): item for item in live}
        for symbol in list(wanted):
            pos = self.executor.existing_position(symbol)
            item = live_by_sym.get(symbol)
            if pos is None and item and float(item.get("size") or 0) > 0:
                pos = ActivePosition(
                    position_id=f"close_{symbol}",
                    asset=symbol,
                    market_index=int(item.get("market_index") or 0),
                    side=item.get("side") or "BUY/LONG",
                    entry_price=float(item.get("entry_price") or 0),
                    size_eth=float(item.get("size") or 0),
                    notional_usd=0.0,
                )
            if pos is None or not pos.is_active:
                if item is None or float(item.get("size") or 0) <= 0:
                    leftover.discard(symbol)
                continue
            mark = prices.get(symbol) or pos.entry_price
            logger.warning("Operator close request for %s @ %s", symbol, mark)
            await self.executor.cancel_open_orders(pos.market_index, [pos.tp_order_index, pos.sl_order_index])
            closed = await self.executor.close_position(pos, mark)
            pos.is_active = not closed
            if closed:
                leftover.discard(symbol)
            try:
                from lighter_telegram import tg_send
                tg_send(
                    f"🧹 <b>Closed {symbol}</b> (false news match / operator request)\n"
                    f"{'flat confirmed' if closed else 'NOT FLAT — retrying'}"
                )
            except Exception:
                pass
        try:
            if leftover:
                path.write_text("\n".join(sorted(leftover)) + "\n", encoding="utf-8")
            elif path.exists():
                path.unlink()
        except OSError:
            pass

    async def _tp_watchdog_loop(self):
        """Monitors active positions every second for Take-Profit and Stop-Loss."""
        while True:
            try:
                if await self.enforce_kill_cancel_flatten():
                    await asyncio.sleep(1.0)
                    continue
                # 1. Automatically adopt & sync all on-chain exchange positions with TP/SL
                prices: Dict[str, float] = await self.executor.sync_and_adopt_all_live_positions()
                for pos in self.executor.active_positions.values():
                    snap = self.tickers.get(pos.asset)
                    if snap and snap.price > 0:
                        prices[pos.asset.upper()] = snap.price
                        if hasattr(self.executor, "volatility_engine") and self.executor.volatility_engine:
                            self.executor.volatility_engine.on_tick(pos.asset, snap.price, timestamp=snap.timestamp)
                harvested = await self.executor.harvest_exchange_exits(prices)
                try:
                    await self._honor_close_requests(prices)
                except Exception as close_err:
                    logger.warning("Close-request file: %s", close_err)
                # ALWAYS re-arm missing TP/SL before anything else
                try:
                    enforce = await self.executor.enforce_exits_on_all_positions()
                    if enforce.get("retried") or enforce.get("armed") or enforce.get("missing_local"):
                        logger.info("Exit enforce %s", enforce)
                except Exception as enf_err:
                    logger.warning("Exit enforce: %s", enf_err)
                try:
                    care = await self.executor.care_open_orders(prices)
                    if care.get("cancelled") or care.get("flattened") or care.get("attached"):
                        logger.info("Order care %s", care)
                except Exception as care_err:
                    logger.debug("Order care skipped: %s", care_err)
                # 2. Dynamic Parabolic Profit Step-Lock Evaluation (+5% -> +3% lock, +10% -> +7.5% lock)
                from parabolic_profit_steplock import calculate_parabolic_steplock
                for pos in list(self.executor.active_positions.values()):
                    if pos.is_active and pos.entry_price > 0:
                        mark = prices.get(pos.asset.upper()) or snap.price if (snap := self.tickers.get(pos.asset)) else 0.0
                        if mark > 0:
                            step_res = calculate_parabolic_steplock(
                                side=pos.side,
                                entry_price=pos.entry_price,
                                current_mark_price=mark,
                                highest_price=getattr(pos, "highest_price", 0.0),
                                lowest_price=getattr(pos, "lowest_price", float("inf")),
                                existing_sl_price=pos.sl_price,
                            )
                            if step_res.is_updated and step_res.new_sl_price > 0:
                                pos.sl_price = step_res.new_sl_price
                                pos.pending_sl_amend = True
                                logger.info(
                                    "🔒 [PARABOLIC STEP-LOCK] %s SL stepped up to $%.4f (Locked: +%.1f%%, Reason: %s)",
                                    pos.asset, pos.sl_price, step_res.locked_profit_pct, step_res.reason
                                )

                events = harvested + await self.executor.check_take_profit_and_stop_loss(prices)
                for pos in list(self.executor.active_positions.values()):
                    if pos.is_active and pos.pending_sl_amend:
                        try:
                            await self.executor.amend_trailing_sl(pos)
                        except Exception as trail_err:
                            logger.debug("Trail SL amend skipped: %s", trail_err)
                for ev in events:
                    pos = self.executor.active_positions.get(ev["pos_id"])
                    if not pos:
                        continue
                    if pos.is_active:
                        already_done = bool(ev.get("already_done"))
                        qty = ev.get("close_qty")
                        kind = str(ev.get("type") or "")
                        partial = (kind.startswith("PARTIAL") or kind == "EXCHANGE_PARTIAL") and not ev.get("full")
                        if not already_done:
                            await self.executor.cancel_open_orders(pos.market_index, [pos.tp_order_index, pos.sl_order_index])
                            exit_submitted = await self.executor.close_position(
                                pos, ev["exit_price"], qty=(qty if partial else None)
                            )
                        else:
                            exit_submitted = True
                        if not exit_submitted:
                            logger.error("TP/SL close not confirmed for %s; leaving position open", pos.position_id)
                            continue
                        if partial and pos.size_eth > 1e-12:
                            pos.tp_hits = max(int(pos.tp_hits or 0), int(ev.get("tp_level") or 0))
                            pos.original_size = pos.original_size or pos.size_eth
                            if pos.tp_hits >= 1:
                                pos.sl_price = pos.entry_price
                                pos.max_hold_seconds = max(pos.max_hold_seconds, 3 * 3600)
                            if pos.tp_hits >= 2:
                                pos.trail_gap_pct = min(pos.trail_gap_pct, max(0.25, pos.trail_gap_pct * 0.65))
                            self.executor.ensure_exit_prices(pos)
                            pos.exchange_tp = pos.exchange_sl = False
                            try:
                                await self.executor.arm_protective_exits(pos, retries=3)
                            except Exception as prot_err:
                                logger.debug("Re-arm TP/SL after partial: %s", prot_err)
                            logger.info(
                                "Scale-out %s %s qty=%s remaining=%s hits=%s next_tp=%s sl@%s",
                                ev.get("type"), pos.asset, qty, pos.size_eth, pos.tp_hits, pos.tp_price, pos.sl_price,
                            )
                        else:
                            pos.is_active = False
                            try:
                                self.news_risk_gate.clear_open_position(pos.asset)
                            except Exception:
                                pass
                    else:
                        exit_submitted = True
                    book_pos = next((item for item in self.positions.active() if item.asset == ev["asset"]), None)
                    if book_pos:
                        self.positions.mark_exit(book_pos.position_id, ev["type"], ev["exit_price"], True)
                    self.news_risk_gate.record_pnl(float(ev.get("pnl_usd") or 0.0))
                    try:
                        self.ledger.record_exit(
                            position_id=ev["pos_id"],
                            exit_price=float(ev["exit_price"]),
                            exit_qty=float(ev.get("close_qty") or pos.size_eth),
                            exit_kind=ev["type"],
                            exit_at=time.time(),
                            taker_fee_bps=float(os.getenv("LIGHTER_TAKER_FEE_BPS", "0")),
                        )
                    except Exception as ledger_err:
                        logger.debug("Trade ledger exit failed: %s", ledger_err)
                    from lighter_telegram import tg_send
                    from lighter_telegram import format_exit_card
                    tg_send(format_exit_card(ev, flat=exit_submitted))
                    try:
                        from email_notifier import email_send_exit_alert
                        email_send_exit_alert(
                            asset=ev.get("asset", "?"),
                            exit_type=str(ev.get("type", "?")),
                            pnl_usd=float(ev.get("pnl_usd") or 0.0),
                            pnl_pct=float(ev.get("pnl_pct") or 0.0),
                            exit_price=float(ev.get("exit_price") or 0.0),
                        )
                    except Exception as eme:
                        logger.warning("Email exit alert error: %s", eme)
                for retry in self.positions.due_retries():
                    pos = self.positions.positions.get(retry.position_id)
                    if not pos:
                        continue
                    if self.executor.existing_position(pos.asset, pos.market_index):
                        self.positions.mark_exit(pos.position_id, "adopted_managed", pos.entry_price, True)
                        continue
                    dummy = ActivePosition(
                        position_id=pos.position_id,
                        asset=pos.asset,
                        market_index=pos.market_index,
                        side=pos.side,
                        entry_price=pos.entry_price,
                        size_eth=pos.size,
                        notional_usd=pos.notional_usd,
                    )
                    mark = prices.get(pos.asset.upper()) or pos.exit_price or pos.entry_price
                    submitted = await self.executor.close_position(dummy, mark)
                    self.positions.mark_exit(pos.position_id, retry.reason, mark, submitted)
            except Exception as e:
                logger.warning("[TP Watchdog Error]: %s", e)
            await asyncio.sleep(1.0)

    async def reconcile_exchange(self) -> None:
        found = await self.executor.fetch_account_positions()
        logger.info("Startup reconcile found %s exchange position(s)", len(found))
        flatten = os.getenv("NEWS_STARTUP_FLATTEN", "false").lower() in {"1", "true", "yes"}
        wanted = [(str(it.get("symbol") or ""), int(it.get("market_index") or 0)) for it in found if it.get("symbol")]
        try:
            books = await self.executor.fetch_order_catalog()
            for asset, snapshot in self.executor.snapshots_from_catalog(books, wanted).items():
                self.tickers.update(snapshot)
        except Exception:
            pass
        for item in found:
            symbol = item["symbol"] or "UNK"
            snap = self.tickers.get(symbol)
            price = item["entry_price"] or (snap.price if snap else 0.0)
            notional = float(item["size"]) * float(price or item["entry_price"] or 1.0)
            if notional < 10.0:
                logger.info("Ignoring residual exchange dust for %s: size=%s ($%.4f USD)", symbol, item["size"], notional)
                continue
            if flatten:
                dummy = ActivePosition(
                    position_id=f"recon_{symbol}",
                    asset=symbol,
                    market_index=item["market_index"],
                    side=item["side"],
                    entry_price=item["entry_price"],
                    size_eth=item["size"],
                    notional_usd=item["size"] * (item["entry_price"] or 1),
                )
                await self.executor.close_position(dummy, price or item["entry_price"])
                logger.warning("Startup flatten submitted for %s", symbol)
                continue
            from trade_exits import already_through_exit, infer_tp_hits, policy_for, scaled_out_qty
            policy = policy_for(symbol)
            entry = item["entry_price"] or price or 0.0
            pos = ActivePosition(
                position_id=f"recon_{symbol}_{int(time.time())}",
                asset=symbol,
                market_index=item["market_index"],
                side=item["side"],
                entry_price=entry,
                size_eth=item["size"],
                notional_usd=item["size"] * (entry or 1),
                highest_price=entry,
                lowest_price=entry,
                original_size=item["size"],
                tp_pct=policy.tp_pct,
                sl_pct=policy.sl_pct,
                max_hold_seconds=policy.max_hold_seconds,
                trail_arm_pct=policy.trail_arm_pct,
                trail_gap_pct=policy.trail_gap_pct,
            )
            self.executor.ensure_exit_prices(pos)
            saved = self.executor.clock.recall(symbol)
            pos.entry_time = self.executor.clock.remember(symbol, saved or pos.entry_time)
            if saved:
                logger.info("Restored hold clock for %s first_seen=%.0fs ago", symbol, time.time() - pos.entry_time)
            self.executor.active_positions[pos.position_id] = pos
            snap_mark = snap.price if snap and snap.price > 0 else entry
            itm = already_through_exit(item["side"], snap_mark, pos.tp_price, pos.sl_price) if snap_mark else None
            hits = infer_tp_hits(item["side"], entry, snap_mark, policy) if snap_mark else 0
            if itm == "STOP_LOSS" and snap_mark:
                logger.info("Adopted %s already through STOP_LOSS @ %s — closing now", symbol, snap_mark)
                await self.executor.cancel_open_orders(pos.market_index, [pos.tp_order_index, pos.sl_order_index])
                closed = await self.executor.close_position(pos, snap_mark)
                pos.is_active = not closed
                continue
            if hits >= 1 and snap_mark:
                qty = scaled_out_qty(pos.original_size, pos.size_eth, hits)
                logger.info("Adopted %s already through TP%s @ %s — catch-up scale qty=%s", symbol, hits, snap_mark, qty)
                await self.executor.cancel_open_orders(pos.market_index, [pos.tp_order_index, pos.sl_order_index])
                if hits >= 4:
                    closed = await self.executor.close_position(pos, snap_mark)
                    pos.is_active = not closed
                    continue
                closed = await self.executor.close_position(pos, snap_mark, qty=qty)
                if closed:
                    pos.tp_hits = hits
                    pos.sl_price = pos.entry_price
                    pos.max_hold_seconds = max(pos.max_hold_seconds, 3 * 3600)
                    self.executor.ensure_exit_prices(pos)
            open_n = int(item.get("open_order_count") or 0)
            if pos.tp_price and pos.sl_price:
                try:
                    protect = await self.executor.sync_position_orders(pos, open_n)
                    logger.info("Adopted %s %s size=%s orders=%s protect=%s", symbol, item["side"], item["size"], open_n, protect.get("detail"))
                except Exception as prot_err:
                    logger.warning("Adopted %s but TP/SL sync failed: %s", symbol, prot_err)
            else:
                logger.info("Adopted exchange position %s %s size=%s (no entry for TP/SL)", symbol, item["side"], item["size"])
        self.reconciled = True
        exch_syms = {str(item.get("symbol") or "").upper() for item in found}
        for book in list(self.positions.active()):
            reason = "adopted_live" if book.asset.upper() in exch_syms else "already_flat"
            self.positions.mark_exit(book.position_id, reason, book.entry_price, True)
        if len(found) > 0 or flatten:
            try:
                from lighter_telegram import tg_send
                tg_send(f"🔁 <b>Reconcile</b> found {len(found)} exchange position(s). flatten={flatten}")
            except Exception:
                pass

    async def sync_lighter_universe(self, notify: bool = True) -> Dict[str, Any]:
        """Refresh Lighter markets, alias new tickers, attach ticker Google News feeds."""
        from news_sources import register_ticker_sources
        from news_universe import ASSET_ALIASES, sync_catalog
        from trade_exits import COMMODITY, CRYPTO, FX, INDEX

        books = await self.executor.fetch_order_catalog()
        if books:
            self.markets.ingest_catalog(books)
        symbols = [market.symbol for market in self.markets.enabled()]
        listed = set(symbols)
        named = FX | INDEX | COMMODITY | CRYPTO | set(ASSET_ALIASES.values())
        new, first = sync_catalog(symbols)
        seed = sorted(named & listed)
        open_syms = [p.asset.upper() for p in self.executor.active_positions.values() if p.is_active]
        # Attach ticker news for EVERY active Lighter market (cap 300; catalog is ~224).
        all_listed = sorted(listed)
        want = list(dict.fromkeys(open_syms + seed + new + all_listed))
        added = register_ticker_sources(self.news_manager.registry, want, limit=300)
        logger.info(
            "Universe sync markets=%s new=%s first=%s ticker_feeds=%s",
            len(symbols), new[:12], first, added,
        )
        if notify and new and not first:
            try:
                from lighter_telegram import tg_send
                shown = ", ".join(new[:30]) + ("…" if len(new) > 30 else "")
                tg_send(f"🆕 <b>New Lighter pairs</b>\n{shown}\n📡 ticker news sources attached")
            except Exception:
                pass
        return {"markets": len(symbols), "new": new, "ticker_feeds": added, "first": first}

    async def _universe_loop(self) -> None:
        interval = float(os.getenv("NEWS_UNIVERSE_SECONDS", str(12 * 3600)))
        while True:
            try:
                await self.sync_lighter_universe(notify=True)
            except Exception as e:
                logger.warning("universe sync: %s", e)
            await asyncio.sleep(max(300.0, interval))

    async def _heartbeat_loop(self) -> None:
        interval = float(os.getenv("NEWS_HEARTBEAT_SECONDS", "300"))
        ping_tg = os.getenv("NEWS_HEARTBEAT_TELEGRAM", "true").lower() in {"1", "true", "yes"}
        while True:
            await asyncio.sleep(interval)
            try:
                for bet in self.scoreboard.due():
                    snap = self.tickers.get(bet.asset)
                    if snap and snap.price > 0:
                        self.scoreboard.settle(bet.bet_id, snap.price)
                board = self.scoreboard.summary()
                collat = await self.executor.fetch_available_collateral_usd()
                active_pos = [p for p in self.executor.active_positions.values() if p.is_active]
                open_n = len(active_pos)

                scan_lines = []
                for p in active_pos:
                    mark = snap.price if (snap := self.tickers.get(p.asset)) else p.entry_price
                    pnl_pct = ((mark - p.entry_price) / p.entry_price * 100.0) if p.side.startswith("BUY") else ((p.entry_price - mark) / p.entry_price * 100.0) if p.entry_price > 0 else 0.0
                    pnl_usd = (pnl_pct / 100.0) * p.notional_usd
                    scan_lines.append(
                        f"  • {p.asset} {p.side}: {p.size_eth} @ ${p.entry_price:.4f} (Mark: ${mark:.4f} | PnL: {'+' if pnl_usd>=0 else ''}${pnl_usd:.2f} / {pnl_pct:+.2f}%)"
                    )

                logger.info(
                    "🔍 [5-MIN POSITION SCAN] mode=%s open=%d collat=$%s | daily_loss=$%.2f | scoreboard %d/%d\n%s",
                    self.mode_label(),
                    open_n,
                    f"{collat:.2f}" if collat is not None else "N/A",
                    self.news_risk_gate._daily_loss_usd,
                    board.get("hits", 0),
                    board.get("closed", 0),
                    "\n".join(scan_lines) if scan_lines else "  (No active positions open)",
                )
                if ping_tg and open_n > 0:
                    from lighter_telegram import tg_send
                    pos_text = "\n".join(scan_lines)
                    tg_send(
                        f"🔍 <b>5-Min Position Scan</b> ({self.mode_label()})\n"
                        f"💼 <b>Collateral:</b> ${collat if collat is not None else 0:.2f} USDC\n"
                        f"📊 <b>Active Positions ({open_n}):</b>\n{pos_text}"
                    )
            except Exception as e:
                logger.debug("heartbeat: %s", e)

    async def run(self):
        mode = self.mode_label()
        logger.info("=" * 60)
        logger.info(f"  LIGHTER NEWS & MANUAL SNIPER BOT ({mode})")
        logger.info("=" * 60)

        # 1. Launch Integrated Fast Telegram Poller IMMEDIATELY for zero-lag command response
        try:
            from lighter_telegram import LighterTelegramBot
            orch = getattr(self, "orchestrator", None)
            tg_ctx = {
                "executor": self.executor,
                "bot": self,
                "bot_instance": self,
                "markets": self.markets,
                "db": getattr(self, "db", None),
                "news_manager": self.news_manager,
                "orchestrator": orch,
                "master_orchestrator": orch,
            }
            self.tg_bot = LighterTelegramBot(tg_ctx)
            asyncio.create_task(self.tg_bot.run_fast_polling())
            logger.info("⚡ [Telegram] Integrated Ultra-Fast Zero-Lag Poller active (/status, /balance, /positions, /help)")
        except Exception as e:
            logger.error("Failed to start integrated Telegram poller: %s", e)

        ready, reasons = self.news_risk_gate.readiness(
            self._authorized(),
            MarketSnapshot("ETH", self.current_market_price, timestamp=time.time()),
            bool(self.markets.enabled()),
        )
        if self.is_live and not ready:
            logger.error("Live readiness failed: %s", "; ".join(reasons))
        try:
            books = await asyncio.wait_for(self.executor.fetch_order_catalog(), timeout=5.0)
            if books:
                self.markets.ingest_catalog(books)
                logger.info("Loaded %s Lighter markets (crypto/equities/FX/commodities)", len(self.markets.enabled()))
        except Exception as e:
            logger.warning("Order catalog fetch non-blocking fallback: %s", e)

        if self.is_live:
            try:
                await asyncio.wait_for(self.executor.prewarm(), timeout=8.0)
                if self.executor.signer_client is None:
                    logger.error("Live mode requested but SignerClient is unavailable — no orders will send")
                else:
                    logger.info("Live signer ready for account #%s", self.executor.account_index)
                await asyncio.wait_for(self.reconcile_exchange(), timeout=5.0)
            except Exception as e:
                logger.warning("Signer / reconciliation fallback: %s", e)

        if self.kill_engaged():
            logger.critical("[KILL] Engaged at startup — running cancel_all + optional flatten")
            await self.enforce_kill_cancel_flatten()

        await self.news_manager.start()
        asyncio.create_task(self._price_loop())
        asyncio.create_task(self._tp_watchdog_loop())
        asyncio.create_task(self._heartbeat_loop())
        # 2. Launch Poke AI Autonomous News Sub-Agent Cluster
        try:
            from poke_news_agent import PokeAINewsAgentCluster
            self.poke_cluster = PokeAINewsAgentCluster(on_records=self.on_incoming_news)
            asyncio.create_task(self.poke_cluster.run_subagent_cycle())
            logger.info("🤖 [Poke AI] Autonomous Sub-Agent News Cluster active (Twitter VIP, Upbit KRW, Binance Launchpool)")
        except Exception as e:
            logger.warning("Poke AI cluster startup fallback: %s", e)

        # Whale tape is started once in NewsIngestionManager.start(); do not spawn a second tracker.

        # 3. Launch Volatility Squeeze, Tri-Arb, Latency Arb & Maritime Geopolitical Sniper
        try:
            from volatility_squeeze_engine import VolatilitySqueezeEngine
            from triangular_arbitrage import TriangularArbitrageScanner
            from latency_arbitrage_engine import LatencyLeadArbitrageEngine
            from maritime_geopolitical_sniper import MaritimeGeopoliticalSniper
            self.volatility_squeeze = VolatilitySqueezeEngine()
            self.triangular_scanner = TriangularArbitrageScanner()
            self.latency_arbitrage = LatencyLeadArbitrageEngine(min_dislocation_bps=12.0)
            
            async def _on_geopolitical_incident(inc):
                for target_asset in inc.target_assets:
                    m = self.markets_by_symbol.get(target_asset)
                    if m is None:
                        continue
                    logger.info("🌍 [MARITIME GEOPOLITICAL SNIPE] %s -> %s (Side: %s, Conf: %.2f)", inc.headline, target_asset, inc.direction, inc.confidence)
                    event = _synthetic_normalized_event(
                        event_id=f"GEO_{inc.incident_id}",
                        source_id="MARITIME_OSINT",
                        publisher="GeopoliticalSniper",
                        headline=inc.headline,
                        body=inc.headline,
                        entities=(target_asset,),
                        event_type=inc.chokepoint_type,
                        direction=inc.direction,
                        confidence=inc.confidence,
                        source_score=0.95,
                        category="GEOPOLITICAL_COMMODITY",
                        guid=inc.incident_id,
                    )
                    await self.handle_normalized_event(event)

            self.maritime_sniper = MaritimeGeopoliticalSniper(on_incident_callback=_on_geopolitical_incident)
            asyncio.create_task(self.maritime_sniper.start())
            logger.info("⚡ [VOL SQUEEZE, TRI-ARB, LATENCY ARB & GEOPOLITICAL SNIPER] All engines active")
        except Exception as ve:
            logger.warning("Vol Squeeze / Tri-Arb / Latency / Maritime startup fallback: %s", ve)

        try:
            while True:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            logger.info("Bot shutting down...")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Lighter News & Manual Catalyst Sniper Bot")
    parser.add_argument("--live", action="store_true", default=True, help="Live order execution (default; always on)")
    parser.add_argument("--margin-pct", type=float, default=85.0, help="Max collateral margin utilization percentage")
    args = parser.parse_args()

    bot = LighterNewsSniperBot(is_live=True, max_margin_pct=args.margin_pct)
    asyncio.run(bot.run())
