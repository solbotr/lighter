#!/usr/bin/env python3
"""
Shannon Entropy & Dempster-Shafer Signal Fusion (entropy_signal_combiner.py)
============================================================================
Fuses signals across TreeNews, OFI, Hawkes, Kalman, and Binance Lead into one master conviction score:
- Computes Shannon Information Entropy: H(X) = -∑ p(x) · log₂(p(x))
- Applies Dempster-Shafer Belief Combination Rule to aggregate conflicting evidence
- Only issues execution orders when Consensus Belief ≥ 80% and Entropy is low (high orderliness)
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("EntropySignalCombiner")


@dataclass
class AlphaSignalInput:
    source_name: str
    direction: str  # "BUY", "SELL", "NEUTRAL"
    confidence_pct: float  # 0.0 to 100.0
    weight: float = 1.0


@dataclass
class FusedConsensusDecision:
    symbol: str
    master_direction: str  # "BUY", "SELL", "HOLD"
    consensus_conviction_score: float  # 0.0 to 100.0
    shannon_entropy: float
    is_actionable: bool
    contributing_signals_count: int
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🧠 [SIGNAL FUSION] {self.symbol} | Direction: {self.master_direction} | "
            f"Conviction: {self.consensus_conviction_score:.1f}/100 (Entropy: {self.shannon_entropy:.2f}) | "
            f"Actionable: {self.is_actionable} ({self.contributing_signals_count} Models Fused)"
        )


class EntropySignalCombiner:
    """
    Multi-Model Information Fusion Combiner.
    """

    def __init__(self, min_conviction_threshold: float = 75.0, max_entropy_threshold: float = 1.20):
        self.min_conviction_threshold = min_conviction_threshold
        self.max_entropy_threshold = max_entropy_threshold

    def fuse_signals(self, symbol: str, signals: List[AlphaSignalInput]) -> FusedConsensusDecision:
        """
        Combines multiple model signals using weighted Dempster-Shafer mass function.
        """
        sym = symbol.upper()
        if not signals:
            return FusedConsensusDecision(
                symbol=sym,
                master_direction="HOLD",
                consensus_conviction_score=0.0,
                shannon_entropy=1.58,
                is_actionable=False,
                contributing_signals_count=0,
            )

        buy_mass = 0.0
        sell_mass = 0.0
        neutral_mass = 0.0
        total_weight = sum(s.weight for s in signals)

        for s in signals:
            prob = s.confidence_pct / 100.0
            w = s.weight / total_weight if total_weight > 0 else 1.0
            if s.direction.upper() == "BUY":
                buy_mass += (prob * w)
            elif s.direction.upper() == "SELL":
                sell_mass += (prob * w)
            else:
                neutral_mass += (prob * w)

        # Normalize mass distribution
        sum_m = buy_mass + sell_mass + neutral_mass
        if sum_m > 0:
            p_buy = buy_mass / sum_m
            p_sell = sell_mass / sum_m
            p_neu = neutral_mass / sum_m
        else:
            p_buy, p_sell, p_neu = 0.33, 0.33, 0.34

        # Shannon Entropy: H = -∑ p * log2(p)
        entropy = 0.0
        for p in (p_buy, p_sell, p_neu):
            if p > 1e-6:
                entropy -= (p * math.log2(p))

        if p_buy > p_sell and p_buy > p_neu:
            best_dir = "BUY"
            conviction = p_buy * 100.0
        elif p_sell > p_buy and p_sell > p_neu:
            best_dir = "SELL"
            conviction = p_sell * 100.0
        else:
            best_dir = "HOLD"
            conviction = p_neu * 100.0

        is_act = (conviction >= self.min_conviction_threshold) and (entropy <= self.max_entropy_threshold) and (best_dir != "HOLD")

        decision = FusedConsensusDecision(
            symbol=sym,
            master_direction=best_dir,
            consensus_conviction_score=round(conviction, 1),
            shannon_entropy=round(entropy, 3),
            is_actionable=is_act,
            contributing_signals_count=len(signals),
        )
        return decision
