# Lighter Observability

Every news event, derived signal, risk decision, order intent, order submission, fill, position change, and reconciliation must be traceable by stable correlation identifiers.

## Required metrics

- News ingestion latency
- Source availability
- Event classification latency
- Signal generation latency
- Signal acceptance/rejection counts
- Rejection reasons
- Market-data freshness
- Order-book freshness
- Execution latency
- Order acknowledgement latency
- Fill latency
- Slippage
- Fees
- Funding
- Realized PnL
- Unrealized PnL
- Drawdown
- Exposure
- Open positions
- API error rate
- WebSocket reconnects
- Queue depth
- Event processing lag
- Risk veto counts
- Kill-switch state

## Alerting

Alerts should distinguish informational, degraded, risk, and emergency states. Emergency conditions must be actionable and must not depend on the trading process remaining healthy.
