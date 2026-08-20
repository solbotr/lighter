# Adaptive Strategy Safeguards

Adaptive behavior must not silently mutate the trading policy in live mode.

## Research-only adaptation

- Parameter candidates are generated offline.
- Changes are versioned.
- Training and evaluation datasets are separated.
- Feature and target timestamps are validated.
- Candidate changes require out-of-sample evaluation.
- Regression thresholds must pass before promotion.
- Rollback artifacts are retained.

## Live safeguards

Live execution uses an immutable approved strategy version. Adaptive components may adjust observations or confidence estimates only within explicit bounded ranges.

No online learner may increase leverage, bypass risk limits, disable safety checks, or change execution permissions.
