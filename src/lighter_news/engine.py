from __future__ import annotations

from .models import MarketSnapshot, NewsEvent, Signal
from .news import NewsDeduplicator, NewsNormalizer
from .risk import RiskEngine
from .signals import EventScorer


class NewsTradingEngine:
    """End-to-end signal pipeline. No exchange writes occur in this layer."""

    def __init__(self):
        self.normalizer = NewsNormalizer()
        self.dedup = NewsDeduplicator()
        self.scorer = EventScorer()
        self.risk = RiskEngine()

    def process(self, event: NewsEvent, markets: dict[str, MarketSnapshot]) -> list[Signal]:
        if not self.dedup.accept(event):
            return []
        signals: list[Signal] = []
        for symbol in event.entities:
            market = markets.get(symbol)
            if market is None:
                continue
            signal = self.scorer.classify(event, market)
            if signal is not None:
                signals.append(signal)
        return sorted(signals, key=lambda signal: signal.score, reverse=True)
