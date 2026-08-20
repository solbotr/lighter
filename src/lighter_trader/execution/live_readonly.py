from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ..domain import MarketSnapshot


@dataclass(frozen=True)
class AccountSnapshot:
    account_index: int
    equity: Decimal
    available_balance: Decimal
    positions: tuple[dict[str, Any], ...]
    observed_at: datetime


@dataclass(frozen=True)
class OpenOrderSnapshot:
    order_index: int
    client_order_index: int
    order_id: str
    client_order_id: str
    market_index: int
    side: str
    status: str
    remaining_base_amount: Decimal
    filled_base_amount: Decimal
    reduce_only: bool


class LighterReadOnlyClient:
    """Read-only facade over the installed official Lighter SDK."""

    def __init__(self, base_url: str, account_index: int | None = None, auth_session=None) -> None:
        if not base_url.startswith("https://"):
            raise ValueError("Lighter base URL must use HTTPS")
        self.base_url = base_url.rstrip("/")
        self.account_index = account_index
        self.auth_session = auth_session
        self._api_client = None
        self._orders = None
        self._accounts = None

    def connect(self) -> None:
        import lighter

        configuration = lighter.Configuration(
            host=self.base_url,
            ignore_operation_servers=True,
        )
        self._api_client = lighter.ApiClient(configuration=configuration)
        self._orders = lighter.OrderApi(self._api_client)
        self._accounts = lighter.AccountApi(self._api_client)

    async def close(self) -> None:
        if self._api_client is not None:
            await self._api_client.close()

    async def market_snapshot(self, symbol: str, market_index: int) -> MarketSnapshot:
        self._require_connected()
        response = await self._orders.order_book_orders(market_id=market_index, limit=250)
        asks = sorted(response.asks, key=lambda order: Decimal(order.price))
        bids = sorted(response.bids, key=lambda order: Decimal(order.price), reverse=True)
        if not asks or not bids:
            raise RuntimeError("Lighter returned an incomplete order book")
        bid = float(Decimal(bids[0].price))
        ask = float(Decimal(asks[0].price))
        if bid <= 0 or ask <= 0 or ask < bid:
            raise RuntimeError("Lighter returned an invalid order book")
        timestamp = datetime.now(timezone.utc)
        return MarketSnapshot(
            symbol=symbol,
            timestamp=timestamp,
            bid=bid,
            ask=ask,
            last=(bid + ask) / 2,
            volume=0.0,
            volatility=0.0,
            bid_depth=float(sum(Decimal(order.remaining_base_amount) * Decimal(order.price) for order in bids)),
            ask_depth=float(sum(Decimal(order.remaining_base_amount) * Decimal(order.price) for order in asks)),
        )

    async def account_snapshot(self) -> AccountSnapshot:
        self._require_connected()
        if self.account_index is None:
            raise ValueError("account_index is required for account reads")
        if self.auth_session is None:
            raise RuntimeError("authenticated account reads require an auth session")
        response = await self._accounts.account(
            by="index",
            value=str(self.account_index),
            active_only=True,
            authorization=self.auth_session.authorization(),
        )
        if not response.accounts:
            raise RuntimeError("Lighter returned no account for the configured index")
        account = response.accounts[0]
        return AccountSnapshot(
            account_index=self.account_index,
            equity=Decimal(account.total_asset_value),
            available_balance=Decimal(account.available_balance),
            positions=tuple(position.model_dump() for position in account.positions),
            observed_at=datetime.now(timezone.utc),
        )

    async def open_orders(self) -> tuple[OpenOrderSnapshot, ...]:
        self._require_connected()
        if self.account_index is None:
            raise ValueError("account_index is required for order reads")
        if self.auth_session is None:
            raise RuntimeError("authenticated active-order reads require an auth session")
        response = await self._orders.account_active_orders(
            authorization=self.auth_session.authorization(),
            account_index=self.account_index,
        )
        return tuple(
            OpenOrderSnapshot(
                order_index=order.order_index,
                client_order_index=order.client_order_index,
                order_id=order.order_id,
                client_order_id=order.client_order_id,
                market_index=order.market_index,
                side=order.side,
                status=order.status,
                remaining_base_amount=Decimal(order.remaining_base_amount),
                filled_base_amount=Decimal(order.filled_base_amount),
                reduce_only=order.reduce_only,
            )
            for order in response.orders
        )

    def _require_connected(self) -> None:
        if self._api_client is None:
            raise RuntimeError("call connect() before using the Lighter read-only client")
