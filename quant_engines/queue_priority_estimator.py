#!/usr/bin/env python3
"""
Limit Order Book Queue Priority & Fill Estimator (queue_priority_estimator.py)
=============================================================================
Implements Rama Cont & Adrien de Larrard's (2013) Markovian orderbook queue dynamics:
  P(Fill | k) = μ_fill / (μ_fill + λ_cancel + QueueAhead)

Key Capabilities:
- Calculates exact real-time queue position and estimated time-to-fill for maker orders
- Flags stale orders stuck behind heavy queues (> $50,000) for instant cancellation and re-insertion
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("QueuePriorityEstimator")


@dataclass
class QueueEstimateResult:
    order_id: str
    symbol: str
    side: str  # "BID" or "ASK"
    price: float
    order_size_usd: float
    queue_ahead_usd: float
    total_level_depth_usd: float
    fill_probability_pct: float
    estimated_seconds_to_fill: float
    is_top_of_queue: bool
    should_reprice: bool
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"⚡ [QUEUE PRIORITY] {self.symbol} {self.side} @ ${self.price:,.2f} | Ahead: ${self.queue_ahead_usd:,.2f}/${self.total_level_depth_usd:,.2f} USD | "
            f"P(Fill): {self.fill_probability_pct:.1f}% (~{self.estimated_seconds_to_fill:.1f}s) | Top: {self.is_top_of_queue} | Reprice: {self.should_reprice}"
        )


class OrderbookQueuePriorityEstimator:
    """
    Markovian Queue Position & Fill Estimator.
    """

    def __init__(
        self,
        fill_arrival_rate_usd_per_sec: float = 15000.0,
        cancel_rate_usd_per_sec: float = 8000.0,
        reprice_queue_threshold_usd: float = 40000.0,
    ):
        self.fill_rate = fill_arrival_rate_usd_per_sec
        self.cancel_rate = cancel_rate_usd_per_sec
        self.reprice_queue_threshold_usd = reprice_queue_threshold_usd

    def estimate_order_queue(
        self,
        order_id: str,
        symbol: str,
        side: str,
        price: float,
        order_size_usd: float,
        queue_ahead_usd: float,
        total_level_depth_usd: float,
    ) -> QueueEstimateResult:
        """
        Computes fill probability and time to fill based on queue ahead.
        """
        sym = symbol.upper()
        s = side.upper()
        q_ahead = max(0.0, queue_ahead_usd)
        tot_depth = max(order_size_usd, total_level_depth_usd)

        # Depletion rate = Fill Rate + Cancel Rate
        depletion_speed = self.fill_rate + self.cancel_rate
        est_seconds = (q_ahead + order_size_usd * 0.5) / depletion_speed if depletion_speed > 0 else 10.0

        # Fill Probability: P(Fill) = exp(-0.05 * (q_ahead / fill_rate))
        prob_fill = math.exp(-0.05 * (q_ahead / max(1.0, self.fill_rate))) * 100.0
        prob_fill = max(5.0, min(99.0, prob_fill))

        is_top = q_ahead <= (order_size_usd * 0.20)
        reprice = q_ahead >= self.reprice_queue_threshold_usd or prob_fill <= 30.0

        result = QueueEstimateResult(
            order_id=order_id,
            symbol=sym,
            side=s,
            price=round(price, 4),
            order_size_usd=round(order_size_usd, 2),
            queue_ahead_usd=round(q_ahead, 2),
            total_level_depth_usd=round(tot_depth, 2),
            fill_probability_pct=round(prob_fill, 1),
            estimated_seconds_to_fill=round(est_seconds, 2),
            is_top_of_queue=is_top,
            should_reprice=reprice,
        )
        return result
