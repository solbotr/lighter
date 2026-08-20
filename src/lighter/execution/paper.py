from __future__ import annotations

from dataclasses import dataclass
from itertools import count


@dataclass(frozen=True)
class OrderIntent:
    market_index: int
    side: str
    notional_usd: float
    signal_id: str


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    intent: OrderIntent
    status: str


class PaperExecutor:
    def __init__(self) -> None:
        self._ids = count(1)
        self.orders: list[PaperOrder] = []
        self._seen_signals: set[str] = set()

    def submit(self, intent: OrderIntent) -> PaperOrder:
        if intent.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if intent.notional_usd <= 0:
            raise ValueError("notional must be positive")
        if intent.signal_id in self._seen_signals:
            raise ValueError("duplicate signal")
        self._seen_signals.add(intent.signal_id)
        order = PaperOrder(f"paper-{next(self._ids)}", intent, "accepted")
        self.orders.append(order)
        return order
