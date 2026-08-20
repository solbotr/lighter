from __future__ import annotations

import re
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import NewsEvent


class NewsDeduplicator:
    """Reject repeated/near-identical headlines before they reach the strategy."""

    def __init__(self, max_age_seconds: int = 300, capacity: int = 20_000):
        self.max_age = timedelta(seconds=max_age_seconds)
        self.seen: dict[str, datetime] = {}
        self.order = deque(maxlen=capacity)

    def accept(self, event: NewsEvent) -> bool:
        now = datetime.now(timezone.utc)
        fingerprint = event.fingerprint()
        previous = self.seen.get(fingerprint)
        if previous and now - previous <= self.max_age:
            return False
        self.seen[fingerprint] = now
        self.order.append(fingerprint)
        if len(self.seen) > self.order.maxlen:
            self.seen = {key: self.seen[key] for key in self.order if key in self.seen}
        return True


class EntityMapper:
    """Conservative keyword/entity mapping. Unknown assets are never traded."""

    DEFAULT_ALIASES = {
        "HYPE": {"hyperliquid", "hyperliquid exchange", "$hype", "hype token"},
        "BTC": {"bitcoin", "btc", "$btc"},
        "ETH": {"ethereum", "ether", "eth", "$eth"},
        "SOL": {"solana", "sol", "$sol"},
        "LIT": {"lighter", "zklighter", "lighter protocol", "$lit"},
    }

    def __init__(self, aliases: dict[str, set[str]] | None = None):
        self.aliases = aliases or self.DEFAULT_ALIASES

    def detect(self, text: str) -> frozenset[str]:
        normalized = " " + re.sub(r"[^a-z0-9$]+", " ", text.lower()) + " "
        found: set[str] = set()
        for symbol, aliases in self.aliases.items():
            for alias in aliases:
                needle = " " + alias.lower() + " "
                if needle in normalized:
                    found.add(symbol)
                    break
        return frozenset(found)


class SourcePolicy:
    """Scores sources and blocks obviously weak/unsafe sources."""

    TRUSTED = {
        "reuters": 1.0,
        "associated press": 0.98,
        "bloomberg": 0.98,
        "official": 1.0,
        "government": 1.0,
        "sec": 1.0,
        "federal reserve": 1.0,
    }

    def score(self, source: str) -> float:
        source_l = source.lower().strip()
        for key, score in self.TRUSTED.items():
            if key in source_l:
                return score
        if "verified" in source_l:
            return 0.8
        if "social" in source_l or "telegram" in source_l:
            return 0.25
        return 0.5


class NewsNormalizer:
    def __init__(self, mapper: EntityMapper | None = None, policy: SourcePolicy | None = None):
        self.mapper = mapper or EntityMapper()
        self.policy = policy or SourcePolicy()

    def normalize(self, *, title: str, body: str, url: str, source: str, published_at: datetime) -> NewsEvent:
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        text = f"{title} {body}"
        return NewsEvent(
            id="",
            title=" ".join(title.split()),
            body=" ".join(body.split()),
            url=url,
            source=source,
            published_at=published_at,
            source_score=self.policy.score(source),
            entities=self.mapper.detect(text),
        )

    def filter_fresh(self, events: Iterable[NewsEvent], max_age_seconds: int = 120) -> list[NewsEvent]:
        now = datetime.now(timezone.utc)
        max_age = timedelta(seconds=max_age_seconds)
        return [e for e in events if timedelta(0) <= now - e.published_at <= max_age]
