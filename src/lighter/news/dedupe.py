from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from .models import NewsEvent

_WORDS = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str) -> str:
    return " ".join(_WORDS.sub(" ", title.lower()).split())


@dataclass
class DedupeIndex:
    similarity_threshold: float = 0.92

    def __post_init__(self) -> None:
        self._titles: list[str] = []
        self._fingerprints: set[str] = set()

    def seen(self, event: NewsEvent) -> bool:
        if event.fingerprint in self._fingerprints:
            return True
        normalized = normalize_title(event.title)
        for previous in self._titles:
            if SequenceMatcher(None, normalized, previous).ratio() >= self.similarity_threshold:
                return True
        return False

    def add(self, event: NewsEvent) -> None:
        self._fingerprints.add(event.fingerprint)
        self._titles.append(normalize_title(event.title))

    def filter_new(self, events: Iterable[NewsEvent]) -> list[NewsEvent]:
        fresh: list[NewsEvent] = []
        for event in events:
            if not self.seen(event):
                self.add(event)
                fresh.append(event)
        return fresh
