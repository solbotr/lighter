from __future__ import annotations

from dataclasses import dataclass
import math

from ..config import Settings
from ..lighter_auth import LighterCredentials, build_signer
from .paper import OrderIntent


class LiveExecutionDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    accepted: bool
    order_id: str | None
    reason: str


@dataclass(frozen=True)
class MarketOrderRequest:
    market_index: int
    client_order_index: int
    base_amount: int
    avg_execution_price: int
    is_ask: bool
    reduce_only: bool = False


def build_market_order_request(
    intent: OrderIntent,
    *,
    client_order_index: int,
    base_amount: int,
    avg_execution_price: int,
    reduce_only: bool = False,
) -> MarketOrderRequest:
    if intent.side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if intent.market_index <= 0:
        raise ValueError("market_index must be positive")
    if intent.notional_usd <= 0 or not math.isfinite(intent.notional_usd):
        raise ValueError("notional must be positive and finite")
    if client_order_index <= 0 or base_amount <= 0 or avg_execution_price <= 0:
        raise ValueError("client order index, base amount, and price must be positive")
    return MarketOrderRequest(
        market_index=intent.market_index,
        client_order_index=client_order_index,
        base_amount=base_amount,
        avg_execution_price=avg_execution_price,
        is_ask=intent.side == "sell",
        reduce_only=reduce_only,
    )


class LighterExecutor:
    """SDK boundary. Production transmission remains manually disabled."""

    def __init__(self, settings: Settings, credentials: LighterCredentials | None = None) -> None:
        self.settings = settings
        self.credentials = credentials
        self._signer = None

    def connect(self) -> None:
        if self.settings.mode != "live":
            return
        if self.credentials is None:
            raise LiveExecutionDisabled("live execution requires Lighter credentials")
        self._signer = build_signer(self.credentials)

    def submit(self, intent: OrderIntent) -> ExecutionResult:
        if self.settings.mode != "live":
            raise LiveExecutionDisabled("live order submission is disabled outside explicit live mode")
        self.connect()
        if intent.side not in {"buy", "sell"} or intent.notional_usd <= 0:
            raise ValueError("invalid order intent")
        raise LiveExecutionDisabled("manual production approval and transmission gate are required")
