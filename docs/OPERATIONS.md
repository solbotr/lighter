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

## Deployment invariant

A process restart must not create duplicate orders. An unavailable dependency must fail closed. Live execution must require an explicit, separately reviewed enablement path.
