# Final Readiness Gates

Completing the upgrade tracker does not mean live trading is automatically safe. The system must pass these acceptance gates before any live deployment.

## Engineering

- Type checks pass
- Unit tests pass
- Integration tests pass
- Failure-injection suite passes
- Dependency/security scans pass
- Configuration validation passes
- Reproducibility checks pass

## Data

- News provenance is complete
- Decision timestamps are valid
- No look-ahead leakage is detected
- Market data is fresh
- Asset mappings are point-in-time correct
- Duplicate/contradictory critical events are handled fail-closed

## Trading

- Paper results are reproducible
- Shadow execution agrees with expected behavior
- Costs and latency are included
- Risk limits are independently enforced
- Order reconciliation is deterministic
- Emergency cancellation/flatten procedures are tested

## Operations

- Monitoring is active
- Alerts are actionable
- Recovery has been rehearsed
- Rollback artifact exists
- Last approved release is recoverable
- Live enablement requires explicit operator approval

## Final principle

The system should prefer **no trade** over an uncertain trade. A strong headline signal is still rejected when data integrity, market state, liquidity, execution certainty, or portfolio risk is unacceptable.
