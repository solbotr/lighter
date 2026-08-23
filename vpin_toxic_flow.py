#!/usr/bin/env python3
"""
VPIN Toxic Order Flow Detector (vpin_toxic_flow.py)
===================================================
Implements Volume-Synchronized Probability of Toxicity (VPIN) based on
Easley, López de Prado, and O'Hara (2012):
  VPIN = ∑_{τ=1}^N |V_τ^B - V_τ^S| / (N × V)

Key Capabilities:
- Fixed-Volume Bucketization (e.g. 50,000 USD volume bars)
- Real-time VPIN Score (0.0 to 1.0)
- Toxic Flow Barrier: If VPIN > 0.65, triggers immediate Anti-Adverse Quoting Pause to prevent toxic fills
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("VPINToxicity")


@dataclass
class VolumeBucket:
    bucket_index: int
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    is_filled: bool = False

    @property
    def absolute_imbalance(self) -> float:
        return abs(self.buy_volume - self.sell_volume)

    @property
    def total_volume(self) -> float:
        return self.buy_volume + self.sell_volume


@dataclass
class VPINState:
    symbol: str
    current_vpin_score: float  # 0.0 to 1.0
    is_toxic_flow_detected: bool
    recommended_action: str  # "PAUSE_MAKER", "NORMAL_QUOTING", "TIGHTEN_SPREADS"
    total_buckets_processed: int
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🛡️ [VPIN TOXICITY] {self.symbol} | VPIN Score: {self.current_vpin_score:.4f} | "
            f"Toxic Flow: {self.is_toxic_flow_detected} | Action: {self.recommended_action}"
        )


class VPINToxicFlowDetector:
    """
    Computes real-time Volume-Synchronized Probability of Toxicity.
    """

    def __init__(
        self,
        bucket_size_usd: float = 25000.0,
        num_buckets: int = 10,
        toxicity_threshold: float = 0.65,
    ):
        self.bucket_size_usd = bucket_size_usd
        self.num_buckets = num_buckets
        self.toxicity_threshold = toxicity_threshold
        self.buckets: Dict[str, deque[VolumeBucket]] = {}
        self.current_open_bucket: Dict[str, VolumeBucket] = {}
        self.bucket_counter: Dict[str, int] = {}

    def push_trade(self, symbol: str, volume_usd: float, side: str) -> VPINState:
        """
        Splits incoming trade volume into standardized volume buckets and updates VPIN.
        """
        sym = symbol.upper()
        if sym not in self.buckets:
            self.buckets[sym] = deque(maxlen=self.num_buckets)
            self.bucket_counter[sym] = 0
            self.current_open_bucket[sym] = VolumeBucket(bucket_index=0)

        open_b = self.current_open_bucket[sym]
        rem_vol = volume_usd
        is_buy = side.upper() == "BUY"

        while rem_vol > 0:
            space = self.bucket_size_usd - open_b.total_volume
            add_vol = min(rem_vol, space)

            if is_buy:
                open_b.buy_volume += add_vol
            else:
                open_b.sell_volume += add_vol

            rem_vol -= add_vol

            # Check if bucket is full
            if open_b.total_volume >= self.bucket_size_usd - 1e-4:
                open_b.is_filled = True
                self.buckets[sym].append(open_b)
                self.bucket_counter[sym] += 1
                open_b = VolumeBucket(bucket_index=self.bucket_counter[sym])
                self.current_open_bucket[sym] = open_b

        # Compute VPIN across completed buckets
        b_list = list(self.buckets[sym])
        if not b_list:
            vpin = 0.0
        else:
            total_imb = sum(b.absolute_imbalance for b in b_list)
            total_v = sum(b.total_volume for b in b_list)
            vpin = total_imb / total_v if total_v > 0 else 0.0

        is_toxic = vpin >= self.toxicity_threshold and len(b_list) >= 3
        action = "PAUSE_MAKER" if is_toxic else ("TIGHTEN_SPREADS" if vpin >= 0.50 else "NORMAL_QUOTING")

        state = VPINState(
            symbol=sym,
            current_vpin_score=round(vpin, 4),
            is_toxic_flow_detected=is_toxic,
            recommended_action=action,
            total_buckets_processed=len(b_list),
        )
        return state
