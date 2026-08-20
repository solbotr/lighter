from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mode: str = "paper"
    news_max_age_seconds: int = 120
    min_signal_score: float = 0.75
    min_confidence: float = 0.70
    max_position_notional: float = 100.0
    max_total_notional: float = 250.0
    max_daily_loss: float = 25.0
    max_spread_bps: float = 50.0
    max_volatility: float = 0.25

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("LIGHTER_MODE", "paper").lower()
        if mode not in {"research", "paper", "shadow", "live"}:
            raise ValueError("LIGHTER_MODE must be research, paper, shadow, or live")
        if mode == "live" and os.getenv("LIGHTER_LIVE_TRADING", "false").lower() != "true":
            raise ValueError("live mode requires LIGHTER_LIVE_TRADING=true")
        return cls(
            mode=mode,
            news_max_age_seconds=int(os.getenv("NEWS_MAX_AGE_SECONDS", "120")),
            min_signal_score=float(os.getenv("MIN_SIGNAL_SCORE", "0.75")),
            min_confidence=float(os.getenv("MIN_SIGNAL_CONFIDENCE", "0.70")),
            max_position_notional=float(os.getenv("MAX_POSITION_NOTIONAL", "100")),
            max_total_notional=float(os.getenv("MAX_TOTAL_NOTIONAL", "250")),
            max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "25")),
            max_spread_bps=float(os.getenv("MAX_SPREAD_BPS", "50")),
            max_volatility=float(os.getenv("MAX_VOLATILITY", "0.25")),
        )
