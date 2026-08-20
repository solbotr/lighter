# Lighter

News-driven automated crypto trading research and execution system for [Lighter](https://lighter.xyz/).

## Architecture

```text
News feeds
  -> validation/provenance
  -> normalization + deduplication
  -> entity/asset mapping
  -> event classification
  -> novelty/materiality/credibility
  -> market reaction confirmation
  -> signal engine
  -> portfolio/risk gates
  -> paper/shadow execution
  -> Lighter execution boundary
  -> reconciliation + audit
```

## Lighter API integration

Authentication follows the official Lighter API-key model: account index + API-key index + API-key private key, with credentials loaded only from the environment. Lighter API keys have read/write capabilities and their own nonces; the official SDK handles nonce management. Auth tokens are time-limited, while read-only auth tokens are separate. See the [official API-key documentation](https://apidocs.lighter.xyz/docs/api-keys).

The repository intentionally keeps the live order boundary fail-closed until the current SDK order method is verified by integration tests.

## Runtime modes

- `research`
- `paper` (default)
- `shadow`
- `live` (requires explicit `LIGHTER_LIVE_TRADING=true`)

Presence of credentials alone never enables live trading.

## Core controls

- Source credibility and provenance
- Stale-news rejection
- Exact and near-duplicate rejection
- Rumor downgrade / veto
- Signal confidence and freshness
- Market spread/volatility gates
- Portfolio exposure and concentration controls
- Daily-loss and leverage limits
- Idempotent paper execution
- Fail-closed live execution boundary
- Recovery/reconciliation requirements
- Audit and release governance

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
cp .env.example .env
pytest -q
```

Never commit `.env` or real API credentials.

## Status

The repository contains the research, signal, risk, paper-execution, authentication, and governance foundation. Live trading is intentionally not claimed as production-ready until the current Lighter SDK order path, reconciliation, and end-to-end integration tests are verified.
