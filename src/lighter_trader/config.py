from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ValueError(f"{name} must be true/false, 1/0, or yes/no")


def _base_url(mode: str) -> str:
    default = "https://testnet.zklighter.elliot.ai" if mode != "live" else ""
    value = os.getenv("LIGHTER_BASE_URL", default).rstrip("/")
    if not value.startswith("https://"):
        raise ValueError("LIGHTER_BASE_URL must use HTTPS")
    if mode == "live" and not value:
        raise ValueError("LIGHTER_BASE_URL is required for live mode")
    return value


@dataclass(frozen=True)
class Settings:
    mode: str = "paper"
    base_url: str = "https://testnet.zklighter.elliot.ai"
    news_max_age_seconds: int = 120
    min_signal_score: float = 0.75
    min_confidence: float = 0.70
    max_position_notional: float = 100.0
    max_total_notional: float = 250.0
    max_daily_loss: float = 25.0
    max_spread_bps: float = 50.0
    max_volatility: float = 0.25
    poll_interval_seconds: float = 2.0
    market_max_age_seconds: float = 30.0

    def validate(self) -> None:
        if self.poll_interval_seconds <= 0:
            raise ValueError("NEWS_POLL_SECONDS must be greater than zero")
        if self.market_max_age_seconds <= 0:
            raise ValueError("MARKET_MAX_AGE_SECONDS must be greater than zero")
        if not 0 <= self.min_signal_score <= 1:
            raise ValueError("MIN_SIGNAL_SCORE must be between 0 and 1")
        if not 0 <= self.min_confidence <= 1:
            raise ValueError("MIN_SIGNAL_CONFIDENCE must be between 0 and 1")
        for name, value in (
            ("MAX_POSITION_NOTIONAL", self.max_position_notional),
            ("MAX_TOTAL_NOTIONAL", self.max_total_notional),
            ("MAX_DAILY_LOSS", self.max_daily_loss),
            ("MAX_SPREAD_BPS", self.max_spread_bps),
            ("MAX_VOLATILITY", self.max_volatility),
        ):
            if value < 0:
                raise ValueError(f"{name} must not be negative")

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("LIGHTER_MODE", "paper").lower()
        if mode not in {"research", "paper", "shadow", "live"}:
            raise ValueError("LIGHTER_MODE must be research, paper, shadow, or live")
        live_trading = _env_bool("LIGHTER_LIVE_TRADING", False)
        if mode == "live" and not live_trading:
            raise ValueError("live mode requires LIGHTER_LIVE_TRADING=true")
        if mode != "live" and live_trading:
            raise ValueError("LIGHTER_LIVE_TRADING=true requires LIGHTER_MODE=live")
        settings = cls(
            mode=mode,
            base_url=_base_url(mode),
            news_max_age_seconds=int(os.getenv("NEWS_MAX_AGE_SECONDS", "120")),
            min_signal_score=float(os.getenv("MIN_SIGNAL_SCORE", "0.75")),
            min_confidence=float(os.getenv("MIN_SIGNAL_CONFIDENCE", "0.70")),
            max_position_notional=float(os.getenv("MAX_POSITION_NOTIONAL", "100")),
            max_total_notional=float(os.getenv("MAX_TOTAL_NOTIONAL", "250")),
            max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "25")),
            max_spread_bps=float(os.getenv("MAX_SPREAD_BPS", "50")),
            max_volatility=float(os.getenv("MAX_VOLATILITY", "0.25")),
            poll_interval_seconds=float(os.getenv("NEWS_POLL_SECONDS", "2")),
            market_max_age_seconds=float(os.getenv("MARKET_MAX_AGE_SECONDS", "30")),
        )
        settings.validate()
        return settings
