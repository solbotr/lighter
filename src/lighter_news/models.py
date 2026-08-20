from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import FrozenSet, Optional

from pydantic import BaseModel, Field, field_validator


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class NewsEvent(BaseModel):
    id: str = ""
    title: str
    body: str = ""
    url: str = ""
    source: str
    published_at: datetime
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_score: float = 0.5
    entities: FrozenSet[str] = frozenset()
    raw_hash: str = ""

    @field_validator("source_score")
    @classmethod
    def valid_source_score(cls, value: float) -> float:
        return min(1.0, max(0.0, value))

    def canonical_text(self) -> str:
        return " ".join((self.title + " " + self.body).lower().split())

    def fingerprint(self) -> str:
        return sha256(self.canonical_text().encode()).hexdigest()


class MarketSnapshot(BaseModel):
    symbol: str
    mid: float
    bid: float
    ask: float
    volume_1m: float = 0.0
    volume_5m: float = 0.0
    return_1m: float = 0.0
    return_5m: float = 0.0
    volatility_5m: float = 0.0
    funding_rate: float = 0.0
    open_interest: float = 0.0
    spread_bps: float = 0.0
    liquidity_usd: float = 0.0
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Signal(BaseModel):
    event_id: str
    symbol: str
    direction: Direction
    confidence: float
    novelty: float
    materiality: float
    source_quality: float
    market_confirmation: float
    crowding_penalty: float = 0.0
    priced_in_penalty: float = 0.0
    rationale: str = ""

    @property
    def score(self) -> float:
        raw = (
            0.22 * self.confidence
            + 0.18 * self.novelty
            + 0.20 * self.materiality
            + 0.15 * self.source_quality
            + 0.25 * self.market_confirmation
            - 0.10 * self.crowding_penalty
            - 0.15 * self.priced_in_penalty
        )
        return min(1.0, max(0.0, raw))


class RiskDecision(BaseModel):
    approved: bool
    reason: str
    notional_usd: float = 0.0
    max_loss_usd: float = 0.0
    max_slippage_bps: float = 0.0


class TradeIntent(BaseModel):
    symbol: str
    direction: Direction
    notional_usd: float
    stop_loss_pct: float
    take_profit_pct: float
    max_slippage_bps: float
    signal_score: float
