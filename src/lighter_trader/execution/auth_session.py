from __future__ import annotations

import time
from dataclasses import dataclass

from ..lighter_auth import LighterCredentials, build_signer


@dataclass(frozen=True)
class AuthToken:
    value: str
    expires_at: float


class LighterAuthSession:
    def __init__(self, credentials: LighterCredentials, refresh_margin_seconds: int = 30) -> None:
        self.credentials = credentials
        self.refresh_margin_seconds = refresh_margin_seconds
        self.signer = build_signer(credentials)
        self.token: AuthToken | None = None

    def refresh(self, lifetime_seconds: int = 600) -> AuthToken:
        if not 60 <= lifetime_seconds <= 600:
            raise ValueError("auth token lifetime must be between 60 and 600 seconds")
        value, error = self.signer.create_auth_token_with_expiry(
            deadline=lifetime_seconds,
            api_key_index=self.credentials.api_key_index,
        )
        if error or not value:
            raise RuntimeError(f"Lighter auth token creation failed: {error or 'empty token'}")
        self.token = AuthToken(value=value, expires_at=time.time() + lifetime_seconds)
        return self.token

    def authorization(self) -> str:
        if self.token is None or time.time() + self.refresh_margin_seconds >= self.token.expires_at:
            self.refresh()
        assert self.token is not None
        return self.token.value
