# Lighter API Key Integration

Lighter API keys are account-scoped signing credentials. Each key has its own API-key index and nonce. The official API documentation currently supports API-key indexes 2–254 for programmatic keys; lower indexes are reserved for Lighter front-end interfaces.

## Environment

Set:

- `LIGHTER_BASE_URL` — mainnet is `https://mainnet.zklighter.elliot.ai`.
- `LIGHTER_ACCOUNT_INDEX` — the Lighter internal account index.
- `LIGHTER_API_KEY_INDEX` — the programmatic API-key index.
- `LIGHTER_API_KEY_PRIVATE_KEY` — the API key's private signing key.
- `LIGHTER_LIVE_TRADING=false` until all readiness gates are explicitly approved.

## Authentication model

The Python SDK's `SignerClient` is initialized with the base URL, an `api_private_keys` mapping keyed by API-key index, and the account index. Auth tokens can be generated with the SDK when authenticated REST or WebSocket access is required. Auth tokens have a maximum lifetime of 8 hours.

Read-only tokens are separate and cannot place trades or request withdrawals; they are preferred for monitoring-only processes.

## Nonces

Nonces are managed per API key. The SDK can manage them automatically. If Lighter's sequential transaction behavior requires multiple execution paths, separate API keys may be used, while preserving independent idempotency and reconciliation controls.

## Security

Lighter API keys can have write permissions and can participate in withdrawal-related operations. Therefore Lighter should use a dedicated trading key, never expose the L1 wallet private key to the trading process, and keep live credentials outside source control.

The application must never treat the presence of an API key as permission to enable live trading.
