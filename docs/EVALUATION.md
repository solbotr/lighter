# Lighter Evaluation Gates

A strategy is not promoted because a backtest is profitable. Promotion requires evidence that the edge survives realistic costs, latency, regime changes, and operational failures.

## Required stages

1. Unit tests
2. Integration tests
3. Historical event replay
4. Out-of-sample validation
5. Walk-forward validation
6. Paper trading
7. Shadow execution
8. Limited canary evaluation
9. Review and rollback criteria

## Promotion blockers

- Look-ahead bias
- Unresolved data leakage
- Unbounded loss behavior
- Missing risk limits
- Unknown order reconciliation
- Duplicate-order risk
- Stale market data
- Unverified critical news
- Material discrepancy between paper and shadow execution
- Missing audit trail
- Unexplained PnL drift

## No automatic promotion

A model or strategy may produce a recommendation for promotion, but deployment to live trading requires an explicit operator-controlled gate.
