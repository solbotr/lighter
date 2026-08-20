from __future__ import annotations

from dataclasses import dataclass

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


class LighterExecutor:
    """Thin Lighter SDK boundary. Live order submission is deliberately explicit."""

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
        if self._signer is None:
            self.connect()
        if intent.side not in {"buy", "sell"} or intent.notional_usd <= 0:
            raise ValueError("invalid order intent")
        # The SDK call is intentionally isolated here so risk/reconciliation gates
        # remain mandatory before this boundary is ever invoked.
        raise NotImplementedError("Wire the current Lighter SDK order method here after integration tests")
