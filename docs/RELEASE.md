# Release Governance

## Release artifacts

Every release candidate should contain:

- Source revision
- Strategy version
- Configuration version
- Dependency lock
- Dataset manifest
- Model/parameter manifest
- Test report
- Backtest report
- Security scan report
- Reproducibility checksum
- Rollback target

## Promotion

Research -> paper -> shadow -> canary -> live is an explicit sequence. Failure at any stage blocks promotion.

## Rollback

Rollback must be possible without rebuilding historical dependencies. The last approved version and its configuration must remain recoverable. Any unexplained production discrepancy should prefer disabling new entries over continuing uncertain execution.
