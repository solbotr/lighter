from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ManualLiveApproval:
    operator: str
    review_reference: str
    approved_at: datetime

    @classmethod
    def issue(cls, operator: str, review_reference: str) -> "ManualLiveApproval":
        if not operator.strip():
            raise ValueError("operator identity is required")
        if not review_reference.strip():
            raise ValueError("review reference is required")
        return cls(operator.strip(), review_reference.strip(), datetime.now(timezone.utc))
