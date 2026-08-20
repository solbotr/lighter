# Lighter Operations

## Runtime modes

Lighter must support explicit `research`, `paper`, `shadow`, and `live` modes. Live mode requires an explicit configuration gate and must never be inferred from the presence of credentials.

## Operational requirements

- UTC timestamps internally
- Monotonic clocks for latency measurements
- Structured JSON logs
- Correlation IDs on every event, signal, order, and execution
- Secrets supplied only through environment/secret managers
- No secrets in logs
- Graceful shutdown
- Startup configuration validation
- Dependency health checks
- Lighter connectivity health check
- News-source health check
- Market-data freshness check
- Account-state freshness check
- Persistent state checkpoints
- Recovery journal
- Idempotent restart recovery
- Kill switch checked before every order
- Risk engine checked before every order
- Order state reconciler
- Position reconciler
- Balance reconciler
- Alerting on invariant violations

## Live execution sequence

Live readiness must proceed in this order:

`configuration -> SDK compatibility preflight -> read-only account/market preflight -> reconciliation -> risk gates -> kill switch clear -> explicit manual approval -> transmission`

The repository currently stops before transmission. The controlled release state machine is:

`PREPARE -> APPROVE -> SUBMIT -> RECONCILE`

`SUBMIT` records `FAIL_CLOSED` and raises until the separately reviewed transmission implementation is enabled. Unknown responses enter `AMBIGUOUS`; they are never retried automatically. Client-order IDs are journaled before approval and cannot be reused after restart. Request construction and signing compatibility checks are non-transmitting; no test or CLI command submits a real order.

## Deployment invariant

A process restart must not create duplicate orders. An unavailable dependency must fail closed. Live execution must require an explicit, separately reviewed enablement path.

Credentials, `LIGHTER_LIVE_TRADING=true`, and manual approval do not bypass unresolved reconciliation, stale data, or the disabled transmission boundary.
