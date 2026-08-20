from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class ApprovalError(RuntimeError):
    pass


def request_digest(*, client_order_id: str, request: dict[str, Any], strategy_version: str) -> str:
    payload = {
        "client_order_id": client_order_id,
        "request": request,
        "strategy_version": strategy_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ManualLiveApproval:
    client_order_id: str
    request_hash: str
    operator: str
    review_reference: str
    strategy_version: str
    approved_at: datetime
    expires_at: datetime
    store_path: str
    consumed: bool = False

    @classmethod
    def issue(
        cls,
        operator: str,
        review_reference: str,
        *,
        client_order_id: str = "legacy",
        request: dict[str, Any] | None = None,
        strategy_version: str = "unversioned",
        ttl_seconds: int = 300,
        store_path: str | os.PathLike[str] = "runtime/live_approvals.json",
    ) -> "ManualLiveApproval":
        if not operator.strip():
            raise ValueError("operator identity is required")
        if not review_reference.strip():
            raise ValueError("review reference is required")
        if not client_order_id.strip():
            raise ValueError("client order ID is required")
        if not 1 <= ttl_seconds <= 3600:
            raise ValueError("approval TTL must be between 1 and 3600 seconds")
        request_hash = request_digest(
            client_order_id=client_order_id,
            request=request or {},
            strategy_version=strategy_version,
        )
        now = datetime.now(timezone.utc)
        approval = cls(
            client_order_id=client_order_id,
            request_hash=request_hash,
            operator=operator.strip(),
            review_reference=review_reference.strip(),
            strategy_version=strategy_version,
            approved_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            store_path=os.fspath(store_path),
        )
        approval._persist()
        return approval

    def verify(self, *, client_order_id: str, request: dict[str, Any], strategy_version: str) -> None:
        if self.consumed:
            raise ApprovalError("manual approval has already been consumed")
        if datetime.now(timezone.utc) >= self.expires_at:
            raise ApprovalError("manual approval has expired")
        if client_order_id != self.client_order_id:
            raise ApprovalError("manual approval client order ID mismatch")
        if strategy_version != self.strategy_version:
            raise ApprovalError("manual approval strategy version mismatch")
        expected = request_digest(
            client_order_id=client_order_id,
            request=request,
            strategy_version=strategy_version,
        )
        if expected != self.request_hash:
            raise ApprovalError("manual approval request hash mismatch")

    def consume(self) -> "ManualLiveApproval":
        if self.consumed:
            raise ApprovalError("manual approval has already been consumed")
        if datetime.now(timezone.utc) >= self.expires_at:
            raise ApprovalError("manual approval has expired")
        consumed = ManualLiveApproval(
            **{**self.__dict__, "consumed": True}
        )
        Path(self.store_path).parent.mkdir(parents=True, exist_ok=True)
        payload = consumed.__dict__.copy()
        payload["approved_at"] = consumed.approved_at.isoformat()
        payload["expires_at"] = consumed.expires_at.isoformat()
        Path(self.store_path).write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return consumed

    def _persist(self) -> None:
        path = Path(self.store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.__dict__.copy()
        payload["approved_at"] = self.approved_at.isoformat()
        payload["expires_at"] = self.expires_at.isoformat()
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
