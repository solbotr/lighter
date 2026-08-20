# Lighter — Upgrade Program

## Tranches 1–5: upgrades 1–500
Completed tracker coverage for baseline hardening, news intelligence, entity mapping, market microstructure, research integrity, runtime reliability, recovery, reconciliation, and operational controls.

## Tranche 6: upgrades 501–600

### Security and secrets
501. Secret source abstraction
502. Environment-secret validation
503. Secret redaction in logs
504. Secret redaction in exceptions
505. Secret redaction in traces
506. Secret redaction in metrics
507. API-key format validation
508. Private-key format validation
509. Credential separation
510. Read-only credential mode
511. Trading credential mode
512. Withdrawal-permission audit
513. Credential rotation procedure
514. Credential age tracking
515. Credential exposure response
516. Least-privilege configuration
517. Production dependency pinning
518. Dependency lockfile validation
519. Dependency inventory
520. SBOM generation requirement
521. Dependency vulnerability scan
522. Static security scan
523. Secret-scanning CI gate
524. Unsafe-config CI gate
525. Debug-mode production guard
526. Insecure-TLS configuration guard
527. TLS certificate validation
528. Request timeout enforcement
529. Retry-bound enforcement
530. Retry-jitter enforcement
531. Malformed-response quarantine
532. Oversized-response rejection
533. Unexpected-content-type rejection
534. Input-schema validation
535. Output-schema validation
536. External-input sanitization
537. URL normalization guard
538. SSRF-safe source policy
539. Outbound-host allowlist
540. Network-egress policy

### Execution security
541. Live-order explicit capability gate
542. Separate live credential gate
543. Pre-submit risk gate
544. Pre-submit account gate
545. Pre-submit market gate
546. Pre-submit freshness gate
547. Pre-submit idempotency gate
548. Symbol allowlist
549. Side validation
550. Quantity validation
551. Price validation
552. Notional validation
553. Leverage validation
554. Reduce-only validation
555. Order-type validation
556. Time-in-force validation
557. Client-order-ID uniqueness
558. Client-order-ID persistence
559. Ambiguous-submit quarantine
560. No-blind-retry rule
561. Exchange-state reconciliation before retry
562. Order acknowledgement validation
563. Fill validation
564. Fill-price sanity check
565. Fill-size sanity check
566. Position-direction sanity check
567. Position-size sanity check
568. Margin sanity check
569. Balance sanity check
570. Exposure sanity check
571. Duplicate-fill rejection
572. Duplicate-order rejection
573. Unknown-order quarantine
574. Unknown-fill quarantine
575. Cancel acknowledgement validation
576. Replace acknowledgement validation
577. Order lifecycle timeout
578. Stuck-order detector
579. Emergency cancellation gate
580. Emergency flatten authorization gate

### Data and incident security
581. Untrusted-news boundary
582. Raw-headline execution prohibition
583. Source provenance requirement
584. Source transformation audit
585. Timestamp validation
586. Content encoding validation
587. Content-size limit
588. Contradictory-critical-data veto
589. Unverifiable-critical-data veto
590. Feed compromise flag
591. Source spoofing detection interface
592. Domain ownership metadata
593. Publisher identity validation
594. Certificate/transport anomaly logging
595. Dependency failure isolation
596. Security incident state
597. Trading-disable-on-incident gate
598. Evidence preservation hook
599. Credential-rotation incident hook
600. Post-incident review record

## Safety invariant
Security controls are defense-in-depth. No external input, credential, classifier, or strategy signal may bypass execution, risk, or reconciliation gates. Live execution remains explicitly opt-in.
