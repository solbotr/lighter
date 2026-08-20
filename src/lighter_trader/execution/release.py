from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .lighter_adapter import ExecutionResult, LiveExecutionDisabled, MarketOrderRequest


class ReleaseStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseRecord:
    client_order_id: str
    phase: str
    request: dict[str, Any]
    updated_at: str
    reason: str = ""


class ExecutionJournal:
    def __init__(self, path: str | os.PathLike[str] = "runtime/execution_journal.jsonl") -> None:
        self.path = Path(path)

    def append(self, record: ReleaseRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record.__dict__, sort_keys=True, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def latest(self, client_order_id: str) -> ReleaseRecord | None:
        if not self.path.exists():
            return None
        latest: ReleaseRecord | None = None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("client_order_id") == client_order_id:
                latest = ReleaseRecord(**payload)
        return latest


class ProductionRelease:
    """Two-phase release state machine with transmission permanently blocked."""

    def __init__(self, journal: ExecutionJournal | None = None) -> None:
        self.journal = journal or ExecutionJournal()

    def prepare(self, client_order_id: str, request: MarketOrderRequest) -> ReleaseRecord:
        self._validate_id(client_order_id)
        existing = self.journal.latest(client_order_id)
        if existing is not None:
            raise ReleaseStateError(f"client order ID already exists: {client_order_id}")
        payload = {
            "market_index": request.market_index,
            "client_order_index": request.client_order_index,
            "base_amount": request.base_amount,
            "avg_execution_price": request.avg_execution_price,
            "is_ask": request.is_ask,
            "reduce_only": request.reduce_only,
        }
        return self._record(client_order_id, "PREPARE", payload)

    def approve(self, client_order_id: str, operator: str, reference: str) -> ReleaseRecord:
        current = self._require(client_order_id, "PREPARE")
        if not operator.strip() or not reference.strip():
            raise ReleaseStateError("operator and review reference are required")
        return self._record(client_order_id, "APPROVE", {**current.request, "operator": operator.strip(), "reference": reference.strip()})

    def submit(self, client_order_id: str) -> ExecutionResult:
        current = self._require(client_order_id, "APPROVE")
        self._record(client_order_id, "FAIL_CLOSED", current.request, "transmission disabled")
        raise LiveExecutionDisabled("production transmission remains manually disabled")

    def reconcile(self, client_order_id: str, status: str) -> ReleaseRecord:
        current = self.journal.latest(client_order_id)
        if current is None:
            raise ReleaseStateError("unknown client order ID")
        normalized = status.lower().strip()
        if normalized not in {"accepted", "open", "partially_filled", "filled", "canceled", "rejected", "unknown"}:
            raise ReleaseStateError(f"unrecognized order status: {status}")
        if normalized == "unknown":
            return self._record(client_order_id, "AMBIGUOUS", current.request, "unknown exchange response")
        return self._record(client_order_id, "RECONCILE", {**current.request, "status": normalized})

    def _require(self, client_order_id: str, phase: str) -> ReleaseRecord:
        current = self.journal.latest(client_order_id)
        if current is None or current.phase != phase:
            raise ReleaseStateError(f"client order must be in {phase} phase")
        return current

    def _record(self, client_order_id: str, phase: str, request: dict[str, Any], reason: str = "") -> ReleaseRecord:
        record = ReleaseRecord(client_order_id, phase, request, datetime.now(timezone.utc).isoformat(), reason)
        self.journal.append(record)
        return record

    @staticmethod
    def _validate_id(client_order_id: str) -> None:
        if not client_order_id or len(client_order_id) > 64 or any(char.isspace() for char in client_order_id):
            raise ReleaseStateError("client order ID must be non-empty, <=64 characters, and contain no whitespace")
