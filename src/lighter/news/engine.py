from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from .models import NewsEvent
from .dedupe import DedupeIndex

_BULLISH = {"approved", "launch", "partnership", "adoption", "integration", "investment", "buy", "support"}
_BEARISH = {"hack", "exploit", "ban", "lawsuit", "delist", "shutdown", "investigation", "sell"}
_RUMOR = {"rumor", "reportedly", "allegedly", "unconfirmed", "sources say"}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@dataclass(frozen=True)
class NewsAssessment:
    event: NewsEvent
    direction: str
    score: float
    confidence: float
    reasons: tuple[str, ...]
    tradable: bool


class NewsEngine:
    def __init__(self, max_age_seconds: int = 120, dedupe: DedupeIndex | None = None) -> None:
        self.max_age_seconds = max_age_seconds
        self.dedupe = dedupe or DedupeIndex()

    def assess(self, event: NewsEvent) -> NewsAssessment | None:
        if event.age_seconds > self.max_age_seconds:
            return None
        if self.dedupe.seen(event):
            return None
        self.dedupe.add(event)
        words = _tokens(f"{event.title} {event.body}")
        bullish = len(words & _BULLISH)
        bearish = len(words & _BEARISH)
        rumor = bool(words & _RUMOR) or event.metadata.get("rumor", "false").lower() == "true"
        if bullish == bearish:
            direction = "flat"
        else:
            direction = "long" if bullish > bearish else "short"
        sentiment = 0.5 + min(0.45, abs(bullish - bearish) * 0.08)
        confidence = min(1.0, 0.45 * event.source_score + 0.35 * sentiment + 0.20 * (0.0 if rumor else 1.0))
        score = min(1.0, confidence * (0.85 if rumor else 1.0))
        reasons = [f"source_score={event.source_score:.2f}", f"age={event.age_seconds:.1f}s"]
        if rumor:
            reasons.append("rumor_downgrade")
        if direction == "flat":
            reasons.append("ambiguous_direction")
        return NewsAssessment(event, direction, score, confidence, tuple(reasons), direction != "flat" and not rumor and score >= 0.75)
