"""Typed environment settings (pydantic v2 / pydantic-settings).

Fail-closed for live: prefer `require_live_ready()` before enabling fills.
Does not hardcode LIGHTER_ACCOUNT_INDEX — live must set it explicitly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class Settings(BaseSettings):
    # Read process env only (apps should call load_dotenv() first).
    # Avoid auto-loading .env here so pytest env mutations stay authoritative.
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    # Execution / safety (live-first production defaults)
    lighter_live: bool = Field(default=True, validation_alias="LIGHTER_LIVE")
    news_kill_switch: bool = Field(default=False, validation_alias="NEWS_KILL_SWITCH")
    news_promotion_mode: str = Field(default="live", validation_alias="NEWS_PROMOTION_MODE")
    news_force_live: bool = Field(default=True, validation_alias="NEWS_FORCE_LIVE")
    # Deprecated: kept for env compat; no longer gates live execution.
    dry_run_default: bool = Field(default=False, validation_alias="DRY_RUN_DEFAULT")

    # Optional account index — no hardcoded live default (e.g. 737649)
    lighter_account_index: Optional[int] = Field(default=None, validation_alias="LIGHTER_ACCOUNT_INDEX")
    lighter_api_private_key: str = Field(default="", validation_alias="LIGHTER_API_PRIVATE_KEY")
    lighter_base_url: str = Field(
        default="https://mainnet.zklighter.elliot.ai",
        validation_alias="LIGHTER_BASE_URL",
    )
    wallet_address: str = Field(default="", validation_alias="WALLET_ADDRESS")

    # Telegram admins: ADMIN_CHAT_ID and/or comma-separated TELEGRAM_ADMIN_IDS
    admin_chat_id: str = Field(default="", validation_alias="ADMIN_CHAT_ID")
    telegram_chat_id: str = Field(default="", validation_alias="TELEGRAM_CHAT_ID")
    telegram_admin_ids: str = Field(default="", validation_alias="TELEGRAM_ADMIN_IDS")
    telegram_token: str = Field(default="", validation_alias="TELEGRAM_TOKEN")

    @field_validator(
        "lighter_live",
        "news_kill_switch",
        "news_force_live",
        "dry_run_default",
        mode="before",
    )
    @classmethod
    def _coerce_bool(cls, v: object) -> bool:
        return _truthy(v)

    @field_validator("news_promotion_mode", mode="before")
    @classmethod
    def _norm_mode(cls, v: object) -> str:
        return (str(v) if v is not None else "live").strip().lower() or "live"

    @field_validator("lighter_account_index", mode="before")
    @classmethod
    def _optional_int(cls, v: object) -> Optional[int]:
        if v is None or v == "":
            return None
        return int(v)

    def telegram_admin_id_list(self) -> List[str]:
        ids: List[str] = []
        for raw in (self.telegram_admin_ids, self.admin_chat_id, self.telegram_chat_id):
            for part in str(raw or "").split(","):
                item = part.strip()
                if item and item not in ids:
                    ids.append(item)
        return ids

    @property
    def promotion_mode(self) -> str:
        return self.news_promotion_mode

    @property
    def kill_switch_engaged(self) -> bool:
        return bool(self.news_kill_switch)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()


def require_live_ready() -> Settings:
    """Fail-closed gate for live trading. Raises RuntimeError if unsafe/incomplete.

    Checks kill switch, account index, API key, and Telegram admins.
    Promotion / paper / dry-run fields are ignored for the live gate.
    """
    s = get_settings()
    if s.news_kill_switch:
        raise RuntimeError("NEWS_KILL_SWITCH is engaged; live trading refused")
    if s.lighter_account_index is None:
        raise RuntimeError("LIGHTER_ACCOUNT_INDEX must be set explicitly for live (no hardcoded default)")
    if not (s.lighter_api_private_key or "").strip():
        raise RuntimeError("LIGHTER_API_PRIVATE_KEY required for live")
    if not s.telegram_admin_id_list():
        raise RuntimeError("Telegram admin id required (ADMIN_CHAT_ID or TELEGRAM_ADMIN_IDS)")
    return s
