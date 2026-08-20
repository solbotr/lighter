from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Mapping, Tuple


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class NewsEvent:
    source: str
    title: str
    published_at: datetime
    url: str = ""
    body: str = ""
    author: str = ""
    entities: Tuple[str, ...] = field(default_factory=tuple)
    tags: Tuple[str, ...] = field(default_factory=tuple)
    source_score: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("source is required")
        if not self.title.strip():
            raise ValueError("title is required")
        object.__setattr__(self, "published_at", _utc(self.published_at))
        if not 0.0 <= self.source_score <= 1.0:
            raise ValueError("source_score must be between 0 and 1")

    @property
    def fingerprint(self) -> str:
        canonical = " ".join(self.title.lower().split())
        return sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def age_seconds(self) -> float:
        return max(0.0, (datetime.now(timezone.utc) - self.published_at).total_seconds())
