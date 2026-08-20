# Lighter Security

## Secrets

- Never commit API keys, private keys, seed phrases, or session tokens.
- Redact secrets from structured logs, exceptions, traces, and metrics.
- Use least-privilege credentials where supported.
- Keep trading credentials separate from read-only credentials.
- Prefer withdrawal-disabled trading credentials.
- Rotate credentials on a defined schedule and after suspected exposure.

## Execution security

- Live execution is opt-in and fail-closed.
- Every order must pass the risk engine immediately before submission.
- Client order IDs must be unique and durable across restarts.
- Never blindly retry an ambiguous order submission.
- Reconcile exchange state before retrying an uncertain request.
- Reject orders with invalid symbol, side, size, price, or reduce-only semantics.
- Enforce maximum notional and leverage independently of strategy output.

## Data integrity

- Treat external news as untrusted input.
- Validate timestamps, encoding, content size, and source identity.
- Never execute directly from raw headlines.
- Keep source provenance and transformations for every signal.
- Fail closed on contradictory or unverifiable critical data.

## Dependency security

- Pin production dependencies.
- Generate dependency inventory/SBOM.
- Run vulnerability scanning in CI.
- Restrict outbound network access where practical.
- Validate TLS certificates.
- Apply request timeouts and bounded retries.
- Quarantine malformed responses.

## Incident response

Security incidents must trigger a persisted alert, trading disablement when appropriate, evidence preservation, credential rotation, and post-incident review.
