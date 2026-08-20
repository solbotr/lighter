from __future__ import annotations

from datetime import datetime, timezone
import re

from .models import Direction, MarketSnapshot, NewsEvent, Signal


POSITIVE = {
    "approval", "approved", "adopt", "adoption", "partnership", "launch", "integration",
    "support", "supports", "buy", "bullish", "investment", "invest", "listing", "listed",
    "reserve", "strategic", "backing", "funding", "growth", "record", "surge", "positive",
}
NEGATIVE = {
    "ban", "banned", "lawsuit", "hack", "hacked", "exploit", "exploit", "fraud", "fraudulent",
    "investigation", "sanction", "sanctions", "delist", "delisted", "sell", "bearish", "loss",
    "outage", "shutdown", "collapse", "warning", "negative", "liquidation",
}


class EventScorer:
    """Deterministic first-pass classifier; an LLM can be added later as a second opinion."""

    def classify(self, event: NewsEvent, market: MarketSnapshot) -> Signal | None:
        if market.symbol not in event.entities:
            return None
        text = event.canonical_text()
        words = set(re.findall(r"[a-z]+", text))
        positive = len(words & POSITIVE)
        negative = len(words & NEGATIVE)
        if positive == negative:
            direction = Direction.FLAT
        else:
            direction = Direction.LONG if positive > negative else Direction.SHORT
        if direction is Direction.FLAT:
            return None

        confidence = min(1.0, 0.45 + 0.08 * abs(positive - negative))
        novelty = 1.0
        age = max(0.0, (datetime.now(timezone.utc) - event.published_at).total_seconds())
        novelty *= max(0.0, 1.0 - age / 180.0)
        materiality = min(1.0, 0.35 + 0.08 * abs(positive - negative))
        confirmation = self._market_confirmation(direction, market)
        priced_in = self._priced_in_penalty(direction, market)
        rationale = f"direction={direction.value}; positive={positive}; negative={negative}; return_1m={market.return_1m:.4f}"
        return Signal(
            event_id=event.id or event.fingerprint(),
            symbol=market.symbol,
            direction=direction,
            confidence=confidence,
            novelty=novelty,
            materiality=materiality,
            source_quality=event.source_score,
            market_confirmation=confirmation,
            priced_in_penalty=priced_in,
            rationale=rationale,
        )

    @staticmethod
    def _market_confirmation(direction: Direction, market: MarketSnapshot) -> float:
        if direction is Direction.LONG:
            aligned = max(0.0, market.return_1m) + max(0.0, market.return_5m)
        else:
            aligned = max(0.0, -market.return_1m) + max(0.0, -market.return_5m)
        return min(1.0, aligned / 0.04)

    @staticmethod
    def _priced_in_penalty(direction: Direction, market: MarketSnapshot) -> float:
        move = market.return_1m if direction is Direction.LONG else -market.return_1m
        if move <= 0.01:
            return 0.0
        if move >= 0.08:
            return 1.0
        return (move - 0.01) / 0.07
