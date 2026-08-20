# Lighter — Upgrade Program

## Tranches 1–7: upgrades 1–700
Completed tracker coverage for baseline hardening, news intelligence, entity mapping, market microstructure, research integrity, runtime reliability, recovery, reconciliation, security, execution controls, and advanced event intelligence.

## Tranche 8: upgrades 701–800

### Portfolio risk
701. Gross exposure limit
702. Net exposure limit
703. Per-asset exposure limit
704. Per-sector exposure limit
705. Correlated-asset exposure limit
706. Portfolio leverage limit
707. Margin-utilization ceiling
708. Available-margin floor
709. Concentration penalty
710. Correlation-aware sizing
711. Volatility-aware sizing
712. Liquidity-aware sizing
713. Slippage-aware sizing
714. Fee-aware sizing
715. Funding-aware sizing
716. Drawdown-aware sizing
717. Daily-loss stop
718. Consecutive-loss stop
719. Maximum open positions
720. Maximum turnover
721. Maximum order rate
722. Maximum capital-at-risk
723. Marginal-risk calculation
724. Portfolio-risk budget
725. Shared-risk bucket
726. Asset-risk bucket
727. Sector-risk bucket
728. Correlation-risk bucket
729. Volatility-risk bucket
730. Liquidity-risk bucket
731. Risk-budget reservation
732. Risk-budget release
733. Risk-budget reconciliation
734. Pre-trade portfolio simulation
735. Post-trade portfolio validation
736. Position concentration check
737. Directional concentration check
738. Correlation shock test
739. Volatility shock test
740. Liquidity shock test

### Adaptive strategy governance
741. Strategy-version registry
742. Immutable approved live version
743. Research-only parameter generation
744. Training/evaluation dataset separation
745. Timestamped feature lineage
746. Target leakage detector
747. Candidate parameter versioning
748. Candidate backtest manifest
749. Candidate out-of-sample gate
750. Regression threshold gate
751. Statistical-significance gate
752. Minimum-sample gate
753. Regime-coverage gate
754. Cost-model gate
755. Latency-model gate
756. Slippage-model gate
757. Paper-validation gate
758. Shadow-validation gate
759. Canary-validation gate
760. Rollback artifact retention
761. Rollback trigger policy
762. Rollback execution gate
763. Online-learning prohibition for permissions
764. Online-learning leverage ceiling
765. Online-learning risk-limit ceiling
766. Bounded confidence adaptation
767. Bounded threshold adaptation
768. Adaptation drift monitor
769. Strategy-performance drift detector
770. Feature-distribution drift detector

### Testing and failure simulation
771. Portfolio-risk unit tests
772. Correlation-risk tests
773. Exposure-limit tests
774. Margin-limit tests
775. Drawdown-limit tests
776. Emergency-flatten tests
777. Restart-with-open-position test
778. Restart-with-open-order test
779. Duplicate-order recovery test
780. Ambiguous-submit recovery test
781. Missing-fill recovery test
782. Delayed-fill recovery test
783. Out-of-order-fill test
784. Stale-account test
785. Stale-market test
786. Stale-news test
787. Conflicting-news test
788. Feed-compromise test
789. API-timeout test
790. WebSocket-disconnect test
791. Reconnect-state test
792. Partial-outage test
793. Full-outage fail-closed test
794. Clock-skew test
795. Event-loop-stall test
796. Memory-pressure test
797. Disk-pressure test
798. Queue-overflow test
799. Kill-switch persistence test
800. Full recovery-drill test

## Safety invariant
Portfolio risk remains independent from strategy confidence. Adaptive components cannot expand capital, leverage, permissions, or safety limits in live mode.
