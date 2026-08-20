# Lighter — Upgrade Program

## Tranches 1–6: upgrades 1–600
Completed tracker coverage for baseline hardening, news intelligence, entity mapping, market microstructure, research integrity, runtime reliability, recovery, reconciliation, security, and execution controls.

## Tranche 7: upgrades 601–700

### Advanced news intelligence
601. Multi-feed ingestion coordinator
602. Feed priority policy
603. Source latency ranking
604. Source reliability score
605. Source historical accuracy score
606. Source independence score
607. Publisher identity graph
608. Author identity graph
609. Primary-source detection
610. Secondary-source detection
611. Syndication-chain detection
612. Quote-origin extraction
613. Claim extraction
614. Claim normalization
615. Claim confidence
616. Claim evidence links
617. Fact/opinion classifier
618. Announcement/rumor classifier
619. New/repeated-information classifier
620. Materiality classifier
621. Novelty classifier
622. Temporal-reference resolver
623. Relative-time normalization
624. Entity co-reference resolution
625. Pronoun/entity resolution
626. Asset co-mention graph
627. Direct-impact classifier
628. Indirect-impact classifier
629. Narrative-spillover classifier
630. Positive-language/economic-impact separation
631. Bullish-impact classifier
632. Bearish-impact classifier
633. Neutral-impact classifier
634. Ambiguous-impact classifier
635. Multi-asset impact ranking
636. Event dependency graph
637. Event predecessor tracking
638. Event successor tracking
639. Event supersession detection
640. Event invalidation propagation

### News manipulation and quality controls
641. Headline sensationalism detector
642. Emotional-language penalty
643. ALL-CAPS penalty
644. Engagement-bait penalty
645. Clickbait pattern detector
646. Bot-amplification flag
647. Coordinated-post flag
648. Social-copy cluster detector
649. Repeated-post suppression
650. Screenshot-evidence downgrade
651. Unverified-source downgrade
652. Anonymous-source downgrade
653. Single-source critical-event veto
654. Contradictory-source veto
655. Retraction propagation
656. Correction propagation
657. Article-edit detection
658. Timestamp anomaly detection
659. Future-timestamp rejection
660. Impossible chronology rejection

### Event reaction and signal governance
661. Event reaction baseline freeze
662. Pre-event contamination detector
663. Market-wide confounder detector
664. BTC confounder detector
665. ETH confounder detector
666. Sector confounder detector
667. Concurrent-news detector
668. Concurrent-event clustering
669. Reaction attribution confidence
670. Event-driven return isolation
671. Event-driven volume isolation
672. Event-driven volatility isolation
673. Reaction persistence threshold
674. Reaction exhaustion threshold
675. Sell-the-news detector
676. Buy-the-rumor detector
677. Delayed-reaction detector
678. Overreaction detector
679. Underreaction detector
680. Gap-and-fade detector
681. Breakout-and-hold detector
682. Failed-breakout detector
683. Mean-reversion confirmation
684. Trend-continuation confirmation
685. Signal expiry policy
686. Signal versioning
687. Signal supersession
688. Signal invalidation
689. Signal audit trail
690. Signal explanation payload

### Strategy evaluation and governance
691. News-quality scorecard
692. Source-quality scorecard
693. Event-type scorecard
694. Asset scorecard
695. Market-regime scorecard
696. Latency scorecard
697. Slippage scorecard
698. Paper-vs-shadow comparison
699. Promotion gate checklist
700. Operator approval gate

## Safety invariant
News intelligence can enrich a signal but cannot directly authorize an order. Critical or contradictory information must fail closed, and live promotion always requires an explicit operator-controlled gate.
