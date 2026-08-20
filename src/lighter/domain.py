from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class SignalState(str, Enum):
    NEW = "new"
    VALIDATED = "validated"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"


@dataclass(frozen=True)
class NewsEvent:
    event_id: str
    title: str
    source: str
    published_at: datetime
    received_at: datetime
    assets: tuple[str, ...] = ()
    credibility: float = 0.0
    surprise: float = 0.0
    sentiment: float = 0.0
    is_rumor: bool = False
    canonical_url: str | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    timestamp: datetime
    bid: float
    ask: float
    last: float
    volume: float
    volatility: float
    bid_depth: float = 0.0
    ask_depth: float = 0.0

    @property
    def spread_bps(self) -> float:
        if self.bid <= 0 or self.ask < self.bid:
            return float("inf")
        return (self.ask - self.bid) / ((self.ask + self.bid) / 2) * 10_000


@dataclass(frozen=True)
class Signal:
    signal_id: str
    event_id: str
    symbol: str
    direction: Direction
    score: float
    confidence: float
    created_at: datetime
    expires_at: datetime
    reasons: tuple[str, ...] = ()
    state: SignalState = SignalState.NEW


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...] = ()
    max_notional: float = 0.0


@dataclass
class PortfolioState:
    equity: float
    daily_pnl: float = 0.0
    open_notional: float = 0.0
    open_positions: int = 0
    consecutive_losses: int = 0
    halted: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)
