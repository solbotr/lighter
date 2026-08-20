from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

from ..domain import Direction, Signal, SignalState
from ..news.engine import NewsAssessment


class SignalEngine:
    def __init__(self, expiry_seconds: int = 120, min_score: float = 0.75, min_confidence: float = 0.70) -> None:
        self.expiry_seconds = expiry_seconds
        self.min_score = min_score
        self.min_confidence = min_confidence

    def build(self, assessment: NewsAssessment, symbol: str) -> Signal | None:
        if not assessment.tradable:
            return None
        if assessment.score < self.min_score or assessment.confidence < self.min_confidence:
            return None
        now = datetime.now(timezone.utc)
        raw = f"{assessment.event.fingerprint}:{symbol}:{now.timestamp()}"
        signal_id = sha256(raw.encode()).hexdigest()[:32]
        direction = Direction.LONG if assessment.direction == "long" else Direction.SHORT
        return Signal(signal_id, assessment.event.fingerprint, symbol, direction, assessment.score, assessment.confidence, now, now + timedelta(seconds=self.expiry_seconds), assessment.reasons, SignalState.VALIDATED)
