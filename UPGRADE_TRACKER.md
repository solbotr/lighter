# Lighter — Upgrade Program

## Tranches 1–4: upgrades 1–400
Completed tracker coverage for baseline hardening, news intelligence, entity mapping, market microstructure, event reaction measurement, signal quality, and research/backtesting integrity.

## Tranche 5: upgrades 401–500

### Runtime and reliability
401. Explicit research mode
402. Explicit paper mode
403. Explicit shadow mode
404. Explicit live mode
405. Live-mode fail-closed default
406. Credential-presence does not enable live mode
407. Startup configuration validation
408. Configuration schema version
409. Configuration checksum
410. Environment validation
411. Required-secret validation
412. Secret-format validation
413. Secret-redaction layer
414. Structured JSON logging
415. Log-level configuration
416. Correlation-ID propagation
417. Event-ID propagation
418. Signal-ID propagation
419. Order-ID propagation
420. Execution-ID propagation
421. UTC timestamp normalization
422. Monotonic latency clock
423. Wall-clock sanity check
424. Clock-drift alert
425. Dependency health registry
426. Lighter API health check
427. Lighter WebSocket health check
428. News-source health registry
429. Market-data freshness monitor
430. Account-state freshness monitor
431. Heartbeat watchdog
432. Event-loop stall detector
433. Memory-pressure monitor
434. CPU-pressure monitor
435. Disk-space monitor
436. File-descriptor monitor
437. Connection-count monitor
438. Queue-depth monitor
439. Processing-lag monitor
440. Backpressure mechanism
441. Bounded event queues
442. Bounded retry queues
443. Dead-letter queue
444. Poison-message quarantine
445. Graceful shutdown handler
446. Signal-drain shutdown
447. Order-drain shutdown
448. Cancellation-on-emergency shutdown
449. Persistent state checkpoint
450. Checkpoint checksum

### Recovery and reconciliation
451. Append-only recovery journal
452. Startup journal replay
453. Journal sequence validation
454. Duplicate-event recovery guard
455. Duplicate-order recovery guard
456. Idempotent order recovery
457. Unknown-order reconciliation
458. Open-order reconciliation
459. Position reconciliation
460. Balance reconciliation
461. Margin reconciliation
462. Funding reconciliation
463. Fee reconciliation
464. PnL reconciliation
465. Local-vs-exchange state diff
466. Reconciliation retry policy
467. Reconciliation escalation
468. Recovery timeout
469. Recovery circuit breaker
470. Recovery audit record
471. Kill-switch persistence
472. Kill-switch startup check
473. Kill-switch pre-order check
474. Risk-engine pre-order check
475. Account-state pre-order check
476. Market-data pre-order check
477. News-signal freshness pre-order check
478. Order-intent expiry
479. Client-order-id persistence
480. Duplicate-client-order detection
481. Unknown-execution quarantine
482. Partial-execution reconciliation
483. Cancel-confirmation reconciliation
484. Replace-confirmation reconciliation
485. Fill deduplication
486. Fill sequence validation
487. Position sign validation
488. Position-size invariant
489. Notional invariant
490. Leverage invariant
491. Margin invariant
492. Daily-loss invariant
493. Exposure invariant
494. Open-position-count invariant
495. Order-rate invariant
496. Cancel-rate invariant
497. Emergency flatten gate
498. Emergency flatten audit trail
499. Recovery metrics
500. Operational readiness checklist

## Safety invariant
Reliability upgrades cannot authorize trading by themselves. Every live order must pass mode, kill-switch, risk, account-state, market-data, signal-freshness, and idempotency gates.
