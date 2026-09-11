#!/usr/bin/env python3
"""
Dedicated X (Twitter) Post Monitor Tool (x_monitor.py)
=====================================================
Monitors breaking posts and statements from key VIP crypto & financial accounts on X.

Endpoints / Protocol:
1. Primary: treg routed endpoint (`treg.x.user.posts` on https://treg.to/call/treg.x.user.posts).
   - In practice served by tikhub (`tikhub.x.user.posts`) or scrapecreators automatically via treg.
   - Automatically handles auth via TREG_TOKEN (`X-Treg-Token`).
2. Secondary Fallback: Direct `tikhub.x.user.posts` via treg (`https://treg.to/call/tikhub.x.user.posts?screen_name=...`).
3. Tertiary Fallback: Official X API v2 endpoint (`https://api.twitter.com/2/tweets/search/recent`) using TWITTER_BEARER_TOKEN.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from typing import Any, Callable, Dict, List, Optional, Sequence
from urllib.parse import unquote

import aiohttp
from dotenv import load_dotenv

load_dotenv(override=False)

from news_sources import RawNewsRecord

logger = logging.getLogger("XPostMonitor")

DEFAULT_TREG_BASE_URL = os.getenv("TREG_BASE_URL", "https://treg.to").rstrip("/")
DEFAULT_TREG_TOKEN = os.getenv("TREG_TOKEN", "").strip()
DEFAULT_TREG_FALLBACKS = [
    tok.strip()
    for tok in os.getenv("TREG_TOKEN_FALLBACKS", "").split(",")
    if tok.strip()
]
DEFAULT_TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", os.getenv("X_BEARER_TOKEN", "")).strip()

# Curated high-conviction VIP accounts for instant breaking crypto & financial intelligence.
# Tier 1 polls fast (every X_FAST_POLL_SEC, default 3s). Tier 2 polls slow
# (every X_SLOW_POLL_SEC, default 15s). Keep tier 1 tight: every extra
# account costs one HTTP round trip per cycle.
TIER1_X_ACCOUNTS = [
    # Crypto breaking wires
    "tier10k",        # DB / Tree News wire
    "Tree_of_Alpha",  # Tree of Alpha direct
    "WatcherGuru",    # Breaking crypto alerts
    "WuBlockchain",   # Breaking Asian & mining news
    "Cointelegraph",  # Breaking crypto news
    "CoinDesk",       # Breaking crypto news
    "TheBlock__",     # Breaking crypto news
    "BSCNews",        # BNB ecosystem + listings
    "SolanaFloor",    # Solana ecosystem + launches
    # Listing bots (directly tradeable)
    "krakenlistings", # Kraken "Now live" announcements
    "BithumbOfficial",# Bithumb new listings
    "CoinbaseAssets", # Coinbase asset listings
    # Security (short catalysts)
    "PeckShieldAlert",# Exploit alerts
    "CertiKAlert",    # Exploit alerts
    "lookonchain",    # Whale & on-chain tracking
    "whale_alert",    # Large on-chain transfers
    "ArkhamIntel",    # Treasury / government movements
    # Stocks / macro breaking wires
    "unusual_whales", # Options flow + breaking equity news
    "zerohedge",      # Macro headlines, fastest aggregator
    "StockMarketNews",# Breaking equity headlines
]

TIER2_X_ACCOUNTS = [
    # Crypto official / listings / data
    "binance",        # Binance Official
    "coinbase",       # Coinbase Official
    "krakenfx",       # Kraken Official
    "okx",            # OKX Official
    "Bybit_Official", # Bybit Official
    "CoinMarketCap",  # CMC listings + alerts
    "CoinGecko",      # Gecko listings + alerts
    "CryptoRank_io",  # Listings + market data
    "ICODrops",       # IDO / new listings
    "FarsideUK",      # Daily ETF flows
    "Lighter_xyz",    # Lighter DEX announcements
    "HyperliquidX",   # Hyperliquid listings
    # People (rare but market-moving)
    "SECgov",         # US SEC Announcements
    "VitalikButerin", # Ethereum founder
    "realDonaldTrump",# Market-moving statements
    "elonmusk",       # Market-moving posts
    "saylor",         # Strategy BTC treasury moves
    "cz_binance",     # CZ market commentary
    "Brian_Armstrong",# Coinbase CEO
    "CathieDWood",    # ARK research threads
    "Justinsuntron",  # TRON listings + announcements
    "MarioNawfal",    # Crypto news + spaces
    # Macro / official
    "federalreserve", # US Federal Reserve
    "USTreasury",     # US Treasury announcements
    "BLS_gov",        # Jobs/CPI data releases
    "NickTimiraos",   # WSJ Fed reporter
    # Stocks wires
    "Bloomberg",      # Bloomberg breaking
    "Reuters",        # Reuters breaking
    "CNBC",           # CNBC breaking
    "WSJ",            # Wall Street Journal
    "FinancialTimes", # FT breaking
    "EarningsWhispers",# Earnings calendar + results
    "DeItaone",       # Equities breaking wire
    "FirstSquawk",    # FX/macro squawk
    "LiveSquawk",     # Macro squawk
    "FinancialJuice", # Breaking headlines
    "KobeissiLetter", # Market commentary
    "GoldTelegraph_", # Gold/commodities flow
]

# Back-compat: the full set, tier 1 first.
DEFAULT_VIP_X_ACCOUNTS = list(dict.fromkeys(TIER1_X_ACCOUNTS + TIER2_X_ACCOUNTS))


class XPostMonitorTool:
    """
    Continuous monitor and on-demand tool for X (Twitter) user posts.
    Routes via treg (`treg.x.user.posts`), falling back to tikhub and xapi v2.
    """

    def __init__(
        self,
        treg_token: Optional[str] = None,
        treg_base_url: Optional[str] = None,
        twitter_bearer: Optional[str] = None,
        accounts: Optional[Sequence[str]] = None,
        on_records: Optional[Callable[[List[RawNewsRecord]], Any]] = None,
        poll_interval: float = 10.0,
        slow_accounts: Optional[Sequence[str]] = None,
        slow_poll_interval: Optional[float] = None,
        treg_fallback_tokens: Optional[Sequence[str]] = None,
    ) -> None:
        primary = (treg_token or DEFAULT_TREG_TOKEN).strip()
        fallbacks = [t.strip() for t in (treg_fallback_tokens or DEFAULT_TREG_FALLBACKS) if t and t.strip()]
        # Ordered token pool: primary first, fallbacks after. Dead tokens are
        # skipped until their cooldown expires (balances can be topped up).
        self.treg_tokens = [t for t in [primary, *fallbacks] if t]
        self._treg_dead_until: Dict[str, float] = {}
        self.treg_base_url = (treg_base_url or DEFAULT_TREG_BASE_URL).rstrip("/")
        self.twitter_bearer = unquote(twitter_bearer or DEFAULT_TWITTER_BEARER_TOKEN).strip()
        if accounts is not None:
            # Explicit list: treat everything as fast tier (old behavior).
            self.fast_accounts = list(accounts)
            self.slow_accounts = list(slow_accounts or [])
        else:
            self.fast_accounts = list(TIER1_X_ACCOUNTS)
            self.slow_accounts = list(TIER2_X_ACCOUNTS)
        self.accounts = list(self.fast_accounts + self.slow_accounts)
        self.on_records = on_records
        self.poll_interval = float(
            os.getenv("X_FAST_POLL_SEC", str(poll_interval or 10.0)) or 10.0
        )
        self.slow_poll_interval = float(
            slow_poll_interval
            if slow_poll_interval is not None
            else os.getenv("X_SLOW_POLL_SEC", "60.0")
        )
        self._seen_tweet_ids: set[str] = set()
        self._cycle = 0
        self.is_running = False

    @property
    def treg_token(self) -> str:
        """Back-compat: the first live token."""
        return self._live_tokens()[0] if self._live_tokens() else ""

    def _live_tokens(self) -> List[str]:
        now = time.time()
        return [t for t in self.treg_tokens if self._treg_dead_until.get(t, 0) <= now]

    def _treg_headers(self, token: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "User-Agent": "LighterXMonitor/1.0",
            "X-Treg-Token": token,
        }

    def _treg_token_dead(self, token: str, reason: str, cooldown_sec: float = 3600.0) -> None:
        self._treg_dead_until[token] = time.time() + cooldown_sec
        logger.warning("[XMonitor] Treg token ...%s %s, failing over (cooldown %.0fm)",
                       token[-4:], reason, cooldown_sec / 60)

    def headers(self) -> Dict[str, str]:
        hdrs = {
            "Content-Type": "application/json",
            "User-Agent": "LighterXMonitor/1.0",
        }
        if self.treg_token:
            hdrs["X-Treg-Token"] = self.treg_token
        return hdrs

    async def fetch_user_posts(
        self,
        username: str,
        limit: int = 10,
        session: Optional[aiohttp.ClientSession] = None,
    ) -> List[RawNewsRecord]:
        """
        Fetches latest tweets for a given username.
        Tries:
        1. treg.x.user.posts (routed endpoint)
        2. tikhub.x.user.posts (direct treg sub-route)
        3. xapi fallback (official X API v2)
        """
        clean_user = username.lstrip("@").strip()
        if not clean_user:
            return []

        own_session = session is None
        if own_session:
            session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=False),
                timeout=aiohttp.ClientTimeout(total=8.0),
            )

        assert session is not None
        try:
            # 1. Primary: treg.x.user.posts (Routed endpoint)
            records = await self._fetch_via_treg_routed(session, clean_user, limit)
            if records:
                return records

            # 2. Secondary Fallback: tikhub.x.user.posts
            records = await self._fetch_via_tikhub(session, clean_user, limit)
            if records:
                return records

            # 3. Tertiary Fallback: official X API v2 (xapi)
            records = await self._fetch_via_xapi(session, clean_user, limit)
            if records:
                return records

            return []
        finally:
            if own_session:
                await session.close()

    async def _fetch_via_treg_routed(
        self,
        session: aiohttp.ClientSession,
        username: str,
        limit: int,
    ) -> List[RawNewsRecord]:
        """Calls routed endpoint treg.x.user.posts, failing over across tokens."""
        live = self._live_tokens()
        if not live:
            logger.debug("[XMonitor] No live TREG tokens, skipping treg.x.user.posts")
            return []

        url = f"{self.treg_base_url}/call/treg.x.user.posts"
        payload = json.dumps({"username": username}).encode("utf-8")

        for token in live:
            started = time.perf_counter()
            try:
                async with session.post(url, data=payload, headers=self._treg_headers(token)) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        served_by = resp.headers.get("x-treg-served-by", "treg.x.user.posts")
                        return self._parse_treg_posts(data, username, route=f"treg_routed ({served_by})", latency=(time.perf_counter() - started) * 1000.0)
                    if resp.status == 402:
                        self._treg_token_dead(token, "out of balance (402)")
                        continue  # try next token, never retry a 402 on the same one
                    if resp.status in (401, 403):
                        self._treg_token_dead(token, f"auth refused ({resp.status})", cooldown_sec=86400.0)
                        continue
                    err_text = await resp.text()
                    logger.debug("[XMonitor] treg.x.user.posts %s returned status %d: %s", username, resp.status, err_text[:200])
                    return []  # provider error: don't burn other tokens on it
            except Exception as exc:
                logger.debug("[XMonitor] treg.x.user.posts %s exception: %s", username, exc)
                return []

        return []

    async def _fetch_via_tikhub(
        self,
        session: aiohttp.ClientSession,
        username: str,
        limit: int,
    ) -> List[RawNewsRecord]:
        """Calls direct tikhub.x.user.posts endpoint through treg, with failover."""
        live = self._live_tokens()
        if not live:
            return []

        url = f"{self.treg_base_url}/call/tikhub.x.user.posts?screen_name={username}"

        for token in live:
            started = time.perf_counter()
            try:
                async with session.get(url, headers=self._treg_headers(token)) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        return self._parse_treg_posts(data, username, route="tikhub.x.user.posts", latency=(time.perf_counter() - started) * 1000.0)
                    if resp.status == 402:
                        self._treg_token_dead(token, "out of balance (402)")
                        continue
                    if resp.status in (401, 403):
                        self._treg_token_dead(token, f"auth refused ({resp.status})", cooldown_sec=86400.0)
                        continue
                    logger.debug("[XMonitor] tikhub.x.user.posts %s returned status %d", username, resp.status)
                    return []
            except Exception as exc:
                logger.debug("[XMonitor] tikhub.x.user.posts %s exception: %s", username, exc)
                return []

        return []

    async def _fetch_via_xapi(
        self,
        session: aiohttp.ClientSession,
        username: str,
        limit: int,
    ) -> List[RawNewsRecord]:
        """Fallback: official X API v2 recent search."""
        if not self.twitter_bearer:
            return []

        url = "https://api.twitter.com/2/tweets/search/recent"
        params = {
            "query": f"from:{username} -is:retweet",
            "max_results": str(max(10, min(100, limit))),
            "tweet.fields": "created_at,author_id",
        }
        headers = {
            "Authorization": f"Bearer {self.twitter_bearer}",
            "User-Agent": "LighterXMonitor/1.0",
        }
        started = time.perf_counter()

        try:
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    records = []
                    now = datetime.now(timezone.utc)
                    for item in data.get("data") or []:
                        text = str(item.get("text") or "").strip()
                        if not text:
                            continue
                        tweet_id = str(item.get("id") or "")
                        title = text.split("\n")[0][:280]
                        records.append(
                            RawNewsRecord(
                                source_id=f"x_{username.lower()}",
                                publisher=f"X (@{username})",
                                title=title,
                                body=text,
                                url=f"https://x.com/{username}/status/{tweet_id}" if tweet_id else "",
                                guid=f"x_{tweet_id or title}",
                                published_at=self._parse_iso(item.get("created_at")),
                                ingested_at=now,
                                trust_score=0.96,
                                category="social",
                                raw={
                                    "adapter": "x",
                                    "route": "xapi_v2",
                                    "username": username,
                                    "tweet_id": tweet_id,
                                    "latency_ms": (time.perf_counter() - started) * 1000.0,
                                },
                            )
                        )
                    return records
        except Exception as exc:
            logger.debug("[XMonitor] xapi fallback %s exception: %s", username, exc)

        return []

    def _parse_treg_posts(
        self,
        data: Dict[str, Any],
        username: str,
        route: str,
        latency: float,
    ) -> List[RawNewsRecord]:
        """Extracts and normalizes tweets from treg or tikhub responses."""
        posts = []
        if isinstance(data, dict):
            output = data.get("output")
            if isinstance(output, dict) and "posts" in output:
                posts = output.get("posts", [])
            elif isinstance(output, list):
                posts = output
            elif "data" in data and isinstance(data.get("data"), list):
                posts = data.get("data", [])
            elif "posts" in data and isinstance(data.get("posts"), list):
                posts = data.get("posts", [])

        records: List[RawNewsRecord] = []
        now = datetime.now(timezone.utc)

        for p in posts:
            if not isinstance(p, dict):
                continue
            legacy = p.get("legacy", {}) if isinstance(p.get("legacy"), dict) else {}
            tweet_id = str(p.get("rest_id") or legacy.get("id_str") or p.get("id") or "")
            text = str(legacy.get("full_text") or p.get("text") or legacy.get("text") or "").strip()
            if not text:
                continue

            created_raw = legacy.get("created_at") or p.get("created_at") or p.get("time")
            pub_time = self._parse_created_at(created_raw)
            title = text.split("\n")[0][:280]

            records.append(
                RawNewsRecord(
                    source_id=f"x_{username.lower()}",
                    publisher=f"X (@{username})",
                    title=title,
                    body=text,
                    url=f"https://x.com/{username}/status/{tweet_id}" if tweet_id else "",
                    guid=f"x_{tweet_id or title}",
                    published_at=pub_time,
                    ingested_at=now,
                    trust_score=0.96,
                    category="social",
                    raw={
                        "adapter": "x",
                        "route": route,
                        "username": username,
                        "tweet_id": tweet_id,
                        "latency_ms": latency,
                    },
                )
            )

        return records

    def _parse_created_at(self, val: Any) -> Optional[datetime]:
        if not val:
            return None
        if isinstance(val, (int, float)):
            if val > 1e11:
                val /= 1000.0
            return datetime.fromtimestamp(val, timezone.utc)
        s = str(val).strip()
        try:
            dt = parsedate_to_datetime(s)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return self._parse_iso(s)

    def _parse_iso(self, val: Any) -> Optional[datetime]:
        if not val:
            return None
        try:
            s = str(val).strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    async def poll_all_accounts(
        self,
        session: aiohttp.ClientSession,
    ) -> List[RawNewsRecord]:
        """Polls monitored accounts concurrently.

        Fast tier every cycle; slow tier every Nth cycle where
        N = slow_interval / fast_interval (min 1).
        """
        self._cycle += 1
        every = max(1, int(round(self.slow_poll_interval / max(0.5, self.poll_interval))))
        due = list(self.fast_accounts)
        if self.slow_accounts and (self._cycle % every == 1):
            due += self.slow_accounts
        tasks = [self.fetch_user_posts(acc, limit=5, session=session) for acc in due]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        new_records: List[RawNewsRecord] = []

        for r_list in results:
            if isinstance(r_list, list):
                for rec in r_list:
                    if rec.guid not in self._seen_tweet_ids:
                        self._seen_tweet_ids.add(rec.guid)
                        new_records.append(rec)

        # Cap memory: forget oldest GUIDs beyond 50k.
        if len(self._seen_tweet_ids) > 50_000:
            self._seen_tweet_ids = set(list(self._seen_tweet_ids)[-25_000:])
        return new_records

    async def run_monitor_loop(self) -> None:
        """Continuous background monitor loop."""
        self.is_running = True
        logger.info(
            "🐦 [XPostMonitor] Started monitoring %d fast + %d slow accounts "
            "(%.0fs / %.0fs) via treg.x.user.posts (fallback: tikhub, xapi)",
            len(self.fast_accounts),
            len(self.slow_accounts),
            self.poll_interval,
            self.slow_poll_interval,
        )
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            while self.is_running:
                try:
                    new_records = await self.poll_all_accounts(session)
                    if new_records and self.on_records:
                        if asyncio.iscoroutinefunction(self.on_records):
                            await self.on_records(new_records)
                        else:
                            self.on_records(new_records)
                except Exception as exc:
                    logger.debug("[XMonitor] Loop transient error: %s", exc)

                await asyncio.sleep(self.poll_interval)


# Convenience function for quick CLI / script execution
async def check_account_posts(username: str, limit: int = 5) -> List[RawNewsRecord]:
    tool = XPostMonitorTool()
    return await tool.fetch_user_posts(username, limit=limit)


if __name__ == "__main__":
    import sys
    user = sys.argv[1] if len(sys.argv) > 1 else "tier10k"
    print(f"Checking X posts for @{user}...")
    records = asyncio.run(check_account_posts(user, limit=5))
    print(f"Result count: {len(records)}")
    for r in records:
        print(f"[{r.guid}] {r.published_at} | {r.title}")
        print(f"URL: {r.url}")
        print(f"Route: {r.raw.get('route')} ({r.raw.get('latency_ms', 0):.1f}ms)")
        print("-" * 50)
