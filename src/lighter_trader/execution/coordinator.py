from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import Settings
from ..domain import MarketSnapshot, PortfolioState, Signal
from .controls import KillSwitch
from .manual_gate import ManualLiveApproval
from .paper import OrderIntent
from .compatibility import require_sdk_compatibility
from .reconciliation import ReconciliationSnapshot
from .lighter_adapter import ExecutionResult, LiveExecutionDisabled


@dataclass(frozen=True)
class Preflight:
    market_observed_at: datetime
    reconciliation: ReconciliationSnapshot


class GuardedLiveCoordinator:
    """Fail-closed live coordinator; real writes remain disabled pending approval."""

    def __init__(self, settings: Settings, kill_switch: KillSwitch, approval: ManualLiveApproval | None = None) -> None:
        if settings.mode != "live":
            raise ValueError("guarded live coordinator requires LIGHTER_MODE=live")
        self.settings = settings
        self.kill_switch = kill_switch
        self.approval = approval
        self.compatibility = require_sdk_compatibility()
        self.preflight: Preflight | None = None

    def set_preflight(self, preflight: Preflight) -> None:
        if not preflight.reconciliation.healthy:
            raise ValueError("reconciliation has unresolved discrepancies")
        self.preflight = preflight

    def submit(
        self,
        intent: OrderIntent,
        *,
        signal: Signal,
        market: MarketSnapshot,
        portfolio: PortfolioState,
    ) -> ExecutionResult:
        state = self.kill_switch.state()
        if state.active:
            raise LiveExecutionDisabled(f"kill switch active: {state.reason}")
        if self.approval is None:
            raise LiveExecutionDisabled("manual live approval is required")
        try:
            self.approval.verify(
                client_order_id=intent.signal_id,
                request={
                    "market_index": intent.market_index,
                    "side": intent.side,
                    "notional_usd": intent.notional_usd,
                    "signal_id": intent.signal_id,
                },
                strategy_version="lighter-trader-v1",
            )
        except Exception as exc:
            raise LiveExecutionDisabled(f"manual live approval invalid: {exc}") from exc
        if self.preflight is None or not self.preflight.reconciliation.healthy:
            raise LiveExecutionDisabled("live preflight reconciliation is not healthy")
        now = datetime.now(timezone.utc)
        market_age = (now - market.timestamp.astimezone(timezone.utc)).total_seconds()
        if market_age > self.settings.market_max_age_seconds or market_age < -5:
            raise LiveExecutionDisabled("market data is stale or from the future")
        if market.bid <= 0 or market.ask <= 0 or market.ask < market.bid:
            raise LiveExecutionDisabled("market data is invalid")
        if signal.expires_at <= now or signal.created_at > now:
            raise LiveExecutionDisabled("signal is expired or from the future")
        if signal.symbol != market.symbol:
            raise LiveExecutionDisabled("signal symbol does not match market")
        if signal.score < self.settings.min_signal_score or signal.confidence < self.settings.min_confidence:
            raise LiveExecutionDisabled("signal quality is below configured thresholds")
        if portfolio.halted or portfolio.daily_pnl <= -abs(self.settings.max_daily_loss):
            raise LiveExecutionDisabled("portfolio risk state blocks new entries")
        if intent.notional_usd <= 0 or intent.notional_usd > self.settings.max_position_notional:
            raise LiveExecutionDisabled("order notional is outside configured limits")
        if portfolio.open_notional + intent.notional_usd > self.settings.max_total_notional:
            raise LiveExecutionDisabled("total notional limit would be exceeded")
        raise LiveExecutionDisabled("live order submission remains disabled until production approval")

    def cancel_all(self) -> None:
        raise LiveExecutionDisabled("live cancellation boundary is not enabled")

    def flatten(self) -> None:
        raise LiveExecutionDisabled("live flatten boundary is not enabled")
