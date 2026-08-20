from __future__ import annotations

from dataclasses import dataclass
from math import exp

from lighter.news.models import NewsEvent


@dataclass(frozen=True)
class Signal:
    direction: int
    score: float
    confidence: float
    reason: str


def freshness_score(age_seconds: float, half_life_seconds: float = 300.0) -> float:
    if age_seconds < 0:
        return 0.0
    return exp(-age_seconds / max(1.0, half_life_seconds))


def score_event(
    event: NewsEvent,
    *,
    sentiment: float,
    surprise: float,
    market_confirmation: float,
    already_priced_in: float,
) -> Signal:
    """Return a bounded research signal; execution must apply risk gates separately."""
    values = (sentiment, surprise, market_confirmation, already_priced_in)
    if any(not -1.0 <= value <= 1.0 for value in values):
        raise ValueError("signal inputs must be in [-1, 1]")

    freshness = freshness_score(event.age_seconds)
    direction = 1 if sentiment > 0 else -1 if sentiment < 0 else 0
    raw = (
        0.35 * abs(sentiment)
        + 0.25 * abs(surprise)
        + 0.25 * max(0.0, market_confirmation)
        + 0.15 * event.source_score
    )
    score = max(0.0, min(1.0, raw * freshness * (1.0 - max(0.0, already_priced_in))))
    confidence = max(0.0, min(1.0, score * (0.5 + 0.5 * event.source_score)))
    reason = "material fresh event with market confirmation"
    if already_priced_in > 0.5:
        reason = "rejected: market appears substantially priced-in"
        score = 0.0
    return Signal(direction=direction, score=score, confidence=confidence, reason=reason)
