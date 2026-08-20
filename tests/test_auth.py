import os

import pytest

from lighter.lighter_auth import LighterAuthError, LighterCredentials


def test_missing_credentials_fail_closed(monkeypatch):
    for name in ("LIGHTER_ACCOUNT_INDEX", "LIGHTER_API_KEY_INDEX", "LIGHTER_API_KEY_PRIVATE_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(LighterAuthError):
        LighterCredentials.from_env()


def test_reserved_api_key_index_rejected(monkeypatch):
    monkeypatch.setenv("LIGHTER_ACCOUNT_INDEX", "1")
    monkeypatch.setenv("LIGHTER_API_KEY_INDEX", "1")
    monkeypatch.setenv("LIGHTER_API_KEY_PRIVATE_KEY", "test")
    with pytest.raises(LighterAuthError):
        LighterCredentials.from_env()
