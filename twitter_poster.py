#!/usr/bin/env python3
"""
Autonomous Twitter / X Broadcaster Engine (twitter_poster.py)
============================================================
Handles automated real-time social broadcasting to Twitter / X:
- High-Conviction Tier-1 Breaking News Snipes
- Daily 24h PnL, Win Rate & Points Volume Milestone Reports
- On-Chain Whale Moves & Cross-DEX Arbitrage Highlights
- Telegram Remote Command Dispatch (/tweet <msg>)
- Safe Rate-Limiter & OAuth 1.0a User Context
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests
from requests_oauthlib import OAuth1

logger = logging.getLogger("TwitterPoster")

DEFAULT_CONSUMER_KEY = "o5zbKYpEqvMFdBdHTk6b90jp1"
DEFAULT_CONSUMER_SECRET = "PT0ZKE3B7au4Fut3HBKxFqkX5cdXXFe8F3b8qmmYxLeQxyV93I"
DEFAULT_ACCESS_TOKEN = "2074881853673324546-e0ZAuVQJl6cfb4rufQeMeu1Y4xMhY4"
DEFAULT_ACCESS_TOKEN_SECRET = "JQHDhuQOCK1ejk1E81bNizyMY0iKnEQugbYCYTgNxSlDh"


@dataclass
class TweetResult:
    success: bool
    tweet_id: Optional[str] = None
    text: str = ""
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class TwitterPosterEngine:
    """
    Asynchronous Twitter / X API v2 posting client with anti-spam rate limiting.
    """

    def __init__(
        self,
        consumer_key: Optional[str] = None,
        consumer_secret: Optional[str] = None,
        access_token: Optional[str] = None,
        access_token_secret: Optional[str] = None,
        min_interval_seconds: float = 60.0,
    ):
        self.consumer_key = consumer_key or os.getenv("TWITTER_CONSUMER_KEY") or DEFAULT_CONSUMER_KEY
        self.consumer_secret = consumer_secret or os.getenv("TWITTER_CONSUMER_SECRET") or DEFAULT_CONSUMER_SECRET
        self.access_token = access_token or os.getenv("TWITTER_ACCESS_TOKEN") or DEFAULT_ACCESS_TOKEN
        self.access_token_secret = access_token_secret or os.getenv("TWITTER_ACCESS_TOKEN_SECRET") or DEFAULT_ACCESS_TOKEN_SECRET
        self.min_interval_seconds = min_interval_seconds
        self.last_post_time = 0.0
        self.total_tweets_posted = 0
        self.enabled = True

    def _get_auth(self) -> OAuth1:
        return OAuth1(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.access_token,
            resource_owner_secret=self.access_token_secret,
        )

    def post_tweet(self, text: str) -> TweetResult:
        """
        Submits a tweet via Twitter API v2 (POST /2/tweets).
        """
        if not self.enabled:
            return TweetResult(success=False, text=text, error="Twitter poster is currently disabled.")

        now = time.time()
        if now - self.last_post_time < self.min_interval_seconds:
            wait_s = int(self.min_interval_seconds - (now - self.last_post_time))
            return TweetResult(
                success=False,
                text=text,
                error=f"Rate limit cooldown active. Please wait {wait_s}s before next tweet.",
            )

        clean_text = text.strip()
        if len(clean_text) > 280:
            clean_text = clean_text[:277] + "..."

        url = "https://api.twitter.com/2/tweets"
        try:
            auth = self._get_auth()
            resp = requests.post(
                url,
                auth=auth,
                json={"text": clean_text},
                headers={"Content-Type": "application/json"},
                timeout=8.0,
            )
            if resp.status_code in (200, 201):
                data = resp.json().get("data", {})
                tweet_id = data.get("id")
                self.last_post_time = time.time()
                self.total_tweets_posted += 1
                logger.info(f"🐦 [Twitter Post Success] ID: {tweet_id} | Text: {clean_text[:60]}...")
                return TweetResult(success=True, tweet_id=tweet_id, text=clean_text)
            else:
                err = f"HTTP {resp.status_code}: {resp.text}"
                logger.warning(f"🐦 [Twitter Post Failed] {err}")
                return TweetResult(success=False, text=clean_text, error=err)
        except Exception as e:
            err = str(e)
            logger.error(f"🐦 [Twitter Post Exception] {err}")
            return TweetResult(success=False, text=clean_text, error=err)

    async def post_tweet_async(self, text: str) -> TweetResult:
        """Non-blocking asynchronous wrapper."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.post_tweet, text)

    def format_catalyst_tweet(
        self,
        headline: str,
        asset: str,
        direction: str,
        source: str,
    ) -> str:
        """Formats a high-impact news catalyst tweet."""
        side_emoji = "🟢 LONG" if direction.upper() in ("BUY", "LONG", "BULLISH") else "🔴 SHORT"
        return (
            f"⚡ #BREAKING TRADING SIGNAL\n\n"
            f"🎯 Asset: ${asset}\n"
            f"📊 Action: {side_emoji}\n"
            f"📰 Headline: {headline[:120]}\n"
            f"📡 Source: {source}\n\n"
            f"🤖 Executed via zkLighter & Hyperliquid | #DeFi #Crypto #Trading"
        )

    def format_daily_pnl_tweet(
        self,
        total_pnl_usd: float,
        win_rate_pct: float,
        farmed_volume_usd: float,
    ) -> str:
        """Formats a daily performance milestone tweet."""
        pnl_icon = "🚀" if total_pnl_usd >= 0 else "🛡️"
        return (
            f"🌅 24H BOT PERFORMANCE SUMMARY {pnl_icon}\n\n"
            f"💰 Daily Net PnL: ${total_pnl_usd:+,.2f} USD\n"
            f"🎯 Strategy Win Rate: {win_rate_pct:.1f}%\n"
            f"🌾 Farmed 0-Fee Volume: ${farmed_volume_usd:,.2f} USD\n\n"
            f"⚡ Powered by zkLighter CLOB & Hyperliquid L1\n"
            f"#zkLighter #Hyperliquid #AlgoTrading"
        )
