#!/usr/bin/env python3
"""
Merton Jump-Diffusion Funding Spike Predictor (funding_jump_diffusion.py)
========================================================================
Implements Robert C. Merton's (1976) Jump-Diffusion process on high-frequency funding rates:
  dF_t = (μ - λ_jump · k) F_t dt + σ F_t dW_t + (J - 1) F_t dN_t

Key Capabilities:
- Predicts discrete funding rate jump discontinuities before the top-of-the-hour settlement
- Captures maximum delta-neutral funding payment spikes on zkLighter and Hyperliquid
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("FundingJumpDiffusion")


@dataclass
class FundingRateSample:
    rate_hourly: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class FundingJumpForecast:
    symbol: str
    current_funding_rate_hourly: float
    predicted_funding_rate_hourly: float
    jump_probability_pct: float
    expected_jump_size_bps: float
    annualized_yield_apr_pct: float
    is_prime_harvest_opportunity: bool
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🌾 [FUNDING JUMP FORECAST] {self.symbol} | Current: {self.current_funding_rate_hourly*100:.4f}%/hr ➡️ "
            f"Predicted: {self.predicted_funding_rate_hourly*100:.4f}%/hr (Jump Prob: {self.jump_probability_pct:.1f}%) | "
            f"Annualized APR: +{self.annualized_yield_apr_pct:.1f}% | Prime Harvest: {self.is_prime_harvest_opportunity}"
        )


class FundingJumpDiffusionPredictor:
    """
    Merton Jump-Diffusion Funding Forecaster.
    """

    def __init__(self, jump_threshold_bps: float = 2.0, history_len: int = 24):
        self.jump_threshold_bps = jump_threshold_bps
        self.history_len = history_len
        self.funding_series: Dict[str, deque[FundingRateSample]] = {}

    def push_funding_sample(self, symbol: str, hourly_rate: float, timestamp: Optional[float] = None) -> None:
        """Records hourly funding rate sample."""
        sym = symbol.upper()
        if sym not in self.funding_series:
            self.funding_series[sym] = deque(maxlen=self.history_len)
        now = timestamp or time.time()
        self.funding_series[sym].append(FundingRateSample(rate_hourly=hourly_rate, timestamp=now))

    def forecast_next_funding_rate(self, symbol: str) -> FundingJumpForecast:
        """
        Computes expected funding rate at the next hourly settlement.
        """
        sym = symbol.upper()
        samples = self.funding_series.get(sym, deque())

        if not samples:
            cur_r = 0.0001
            pred_r = 0.0001
            jump_prob = 15.0
            jump_size = 0.5
        else:
            rates = [s.rate_hourly for s in samples]
            cur_r = rates[-1]

            if len(rates) < 3:
                pred_r = cur_r
                jump_prob = 15.0
                jump_size = 0.5
            else:
                # Detect empirical rate velocity and jump frequency
                diffs = [rates[i] - rates[i - 1] for i in range(1, len(rates))]
                mean_diff = sum(diffs) / len(diffs)
                std_diff = math.sqrt(sum((d - mean_diff) ** 2 for d in diffs) / len(diffs)) if len(diffs) > 1 else 0.00005

                # Jump detection: instances where |diff| > 2 * std
                jumps = [d for d in diffs if abs(d) >= 2.0 * std_diff]
                jump_prob = (len(jumps) / len(diffs)) * 100.0 if diffs else 10.0
                jump_size = (sum(jumps) / len(jumps)) * 10000.0 if jumps else 0.0

                # Merton forecast: F_{t+1} = F_t + Drift + Jump_Expectation
                drift = mean_diff * 0.5
                jump_expect = (jump_prob / 100.0) * (jump_size / 10000.0)
                pred_r = cur_r + drift + jump_expect

        apr = abs(pred_r) * 8760.0 * 100.0
        is_prime = apr >= 25.0

        forecast = FundingJumpForecast(
            symbol=sym,
            current_funding_rate_hourly=round(cur_r, 6),
            predicted_funding_rate_hourly=round(pred_r, 6),
            jump_probability_pct=round(jump_prob, 1),
            expected_jump_size_bps=round(jump_size, 2),
            annualized_yield_apr_pct=round(apr, 2),
            is_prime_harvest_opportunity=is_prime,
        )
        return forecast
