#!/usr/bin/env python3
"""
Unit Tests for Twitter / X Poster Engine (test_twitter_poster.py)
================================================================
"""

from __future__ import annotations

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from twitter_poster import TwitterPosterEngine, TweetResult


def test_twitter_poster_initialization():
    poster = TwitterPosterEngine()
    assert poster.consumer_key == "o5zbKYpEqvMFdBdHTk6b90jp1"
    assert poster.enabled is True


def test_twitter_format_catalyst_tweet():
    poster = TwitterPosterEngine()
    text = poster.format_catalyst_tweet(
        headline="Binance lists SOL perpetual contracts",
        asset="SOL",
        direction="BUY",
        source="TreeNews",
    )
    assert "#BREAKING" in text
    assert "$SOL" in text
    assert "🟢 LONG" in text
    assert len(text) <= 280


def test_twitter_format_daily_pnl_tweet():
    poster = TwitterPosterEngine()
    text = poster.format_daily_pnl_tweet(
        total_pnl_usd=124.50,
        win_rate_pct=85.0,
        farmed_volume_usd=45000.0,
    )
    assert "24H BOT PERFORMANCE SUMMARY" in text
    assert "$+124.50" in text
    assert "85.0%" in text
    assert len(text) <= 280
