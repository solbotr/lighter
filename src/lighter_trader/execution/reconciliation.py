from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

_VALID_STATUSES = {"in-progress", "pending", "open", "filled", "canceled", "canceled-post-only", "canceled-reduce-only", "canceled-position-not-allowed", "canceled-margin-not-allowed", "canceled-too-much-slippage", "canceled-not-enough-liquidity", "canceled-self-trade", "canceled-expired", "canceled-oco", "canceled-child", "canceled-liquidation", "canceled-invalid-balance"}

from .live_readonly import AccountSnapshot, OpenOrderSnapshot


@dataclass(frozen=True)
class ReconciliationSnapshot:
    account: AccountSnapshot
    open_orders: tuple[OpenOrderSnapshot, ...]
    discrepancies: tuple[str, ...]
    observed_at: str

    @property
    def healthy(self) -> bool:
        return not self.discrepancies


def reconcile_expected_orders(
    expected_client_order_ids: Iterable[str],
    account: AccountSnapshot,
    open_orders: tuple[OpenOrderSnapshot, ...],
    observed_at: str,
) -> ReconciliationSnapshot:
    expected = set(expected_client_order_ids)
    actual = {order.client_order_id for order in open_orders}
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    discrepancies = [
        f"missing_order:{value}" for value in missing
    ] + [f"unexpected_order:{value}" for value in unexpected]
    if len(actual) != len(open_orders):
        discrepancies.append("duplicate_client_order_id")
    for order in open_orders:
        if order.status not in _VALID_STATUSES:
            discrepancies.append(f"unknown_order_status:{order.status}")
    age = (datetime.now(timezone.utc) - account.observed_at.astimezone(timezone.utc)).total_seconds()
    if age > 30 or age < -5:
        discrepancies.append("stale_account_snapshot")
    discrepancies = tuple(sorted(discrepancies))
    return ReconciliationSnapshot(account, open_orders, discrepancies, observed_at)
