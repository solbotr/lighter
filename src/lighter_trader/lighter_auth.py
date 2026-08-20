"""Lighter API-key authentication primitives.

Credentials are intentionally loaded from environment variables and are never
logged. Live trading is not enabled by this module; it only constructs the
SDK signer/auth configuration after explicit validation.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


class LighterAuthError(ValueError):
    """Raised when Lighter authentication configuration is unsafe/invalid."""


@dataclass(frozen=True)
class LighterCredentials:
    base_url: str
    account_index: int
    api_key_index: int
    api_key_private_key: str

    @classmethod
    def from_env(cls) -> "LighterCredentials":
        base_url = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai").rstrip("/")
        account_raw = os.getenv("LIGHTER_ACCOUNT_INDEX")
        key_index_raw = os.getenv("LIGHTER_API_KEY_INDEX")
        private_key = os.getenv("LIGHTER_API_PRIVATE_KEY")
        legacy_private_key = os.getenv("LIGHTER_API_KEY_PRIVATE_KEY")
        if private_key and legacy_private_key and private_key != legacy_private_key:
            raise LighterAuthError("conflicting Lighter private-key environment variables")
        private_key = private_key or legacy_private_key

        if not account_raw or not key_index_raw or not private_key:
            raise LighterAuthError(
                "Missing LIGHTER_ACCOUNT_INDEX, LIGHTER_API_KEY_INDEX, or "
                "LIGHTER_API_KEY_PRIVATE_KEY"
            )
        try:
            account_index = int(account_raw)
            api_key_index = int(key_index_raw)
        except ValueError as exc:
            raise LighterAuthError("Lighter account/key indexes must be integers") from exc

        # Lighter reserves low API-key indexes for its front-end interfaces.
        if not 2 <= api_key_index <= 254:
            raise LighterAuthError("LIGHTER_API_KEY_INDEX must be in the supported trading-key range 2..254")
        if account_index < 0:
            raise LighterAuthError("LIGHTER_ACCOUNT_INDEX must be non-negative")
        if not private_key.strip():
            raise LighterAuthError("LIGHTER_API_KEY_PRIVATE_KEY cannot be empty")
        if not base_url.startswith("https://"):
            raise LighterAuthError("LIGHTER_BASE_URL must use HTTPS")

        return cls(base_url, account_index, api_key_index, private_key)


def build_signer(credentials: LighterCredentials):
    """Build the official Python SDK SignerClient lazily.

    The SDK is optional at import time so research-only environments do not
    require trading dependencies. The caller remains responsible for the
    separate live-mode/risk gates before submitting transactions.
    """
    try:
        import lighter
    except ImportError as exc:
        raise LighterAuthError("Install lighter-sdk before creating a Lighter signer") from exc

    return lighter.SignerClient(
        url=credentials.base_url,
        api_private_keys={credentials.api_key_index: credentials.api_key_private_key},
        account_index=credentials.account_index,
    )
