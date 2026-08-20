from __future__ import annotations

import os
from typing import Any


class LighterAdapter:
    """Thin safety wrapper around the official Lighter Python SDK.

    The SDK exposes REST/WebSocket market data and signed order operations.
    Live order submission is deliberately disabled unless explicitly enabled
    in the environment after paper validation.
    """

    def __init__(self, *, live_enabled: bool = False, testnet: bool = True):
        self.live_enabled = live_enabled and os.getenv("LIGHTER_LIVE_TRADING", "0") == "1"
        self.testnet = testnet
        self.host = (
            "https://testnet.zklighter.elliot.ai"
            if testnet
            else "https://mainnet.zklighter.elliot.ai"
        )
        self._client: Any = None
        self._api: Any = None

    async def connect_readonly(self) -> None:
        import lighter
        self._api = lighter.ApiClient(configuration=lighter.Configuration(host=self.host))

    async def close(self) -> None:
        if self._api is not None:
            await self._api.close()
            self._api = None
        self._client = None

    async def get_market_snapshot(self, market_id: int) -> Any:
        if self._api is None:
            await self.connect_readonly()
        import lighter
        return await lighter.OrderApi(self._api).order_book_orders(market_id=market_id, limit=100)

    def require_live(self) -> None:
        if not self.live_enabled:
            raise RuntimeError(
                "Live trading is disabled. Set LIGHTER_LIVE_TRADING=1 only after "
                "paper/backtest validation and explicit risk review."
            )

    async def place_market_order(self, **kwargs: Any) -> Any:
        self.require_live()
        if self._client is None:
            raise RuntimeError("SignerClient is not initialized; configure credentials explicitly.")
        return await self._client.create_market_order(**kwargs)
