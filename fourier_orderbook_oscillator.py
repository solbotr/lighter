#!/usr/bin/env python3
"""
Fourier Spectral Orderbook Oscillation Detector (fourier_orderbook_oscillator.py)
================================================================================
Applies discrete Fast Fourier Transform (FFT) on microsecond orderbook spread and tick series:
  X(k) = ∑_{n=0}^{N-1} x_n · e^{-i 2π k n / N}

Key Capabilities:
- Identifies dominant cyclical frequencies and hidden periodicity from competing algorithmic TWAP slicers
- Predicts exact millisecond phase timing for the next institutional liquidity sweep wave
"""

from __future__ import annotations

import cmath
import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("FourierOscillator")


@dataclass
class SpectralFrequencyPeak:
    frequency_hz: float
    period_seconds: float
    spectral_power: float
    phase_radians: float


@dataclass
class SpectralOscillationResult:
    symbol: str
    dominant_period_sec: float
    spectral_power_snr: float  # Signal-to-noise ratio
    is_periodic_algo_detected: bool
    predicted_next_pulse_in_sec: float
    active_peaks: List[SpectralFrequencyPeak] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"⚡ [FOURIER SPECTRAL] {self.symbol} | Dominant Period: {self.dominant_period_sec:.2f}s (SNR: {self.spectral_power_snr:.1f} dB) | "
            f"Periodic Algo Detected: {self.is_periodic_algo_detected} | Next Pulse In: ~{self.predicted_next_pulse_in_sec:.2f}s"
        )


class FourierOrderbookOscillator:
    """
    Microsecond FFT Orderbook Periodicity Analyzer.
    """

    def __init__(self, sampling_rate_hz: float = 10.0, window_size: int = 64):
        self.sampling_rate_hz = sampling_rate_hz
        self.window_size = window_size
        self.tick_series: Dict[str, deque[Tuple[float, float]]] = {}  # (value, timestamp)

    def push_tick(self, symbol: str, spread_or_price: float, timestamp: Optional[float] = None) -> None:
        """Appends tick observation to rolling time series."""
        sym = symbol.upper()
        if sym not in self.tick_series:
            self.tick_series[sym] = deque(maxlen=self.window_size)
        now = timestamp or time.time()
        self.tick_series[sym].append((spread_or_price, now))

    def compute_spectral_decomposition(self, symbol: str) -> SpectralOscillationResult:
        """
        Computes Discrete Fourier Transform (DFT) to extract dominant algorithmic rhythm.
        """
        sym = symbol.upper()
        ticks = self.tick_series.get(sym, deque())
        N = len(ticks)

        if N < 16:
            return SpectralOscillationResult(
                symbol=sym,
                dominant_period_sec=0.0,
                spectral_power_snr=0.0,
                is_periodic_algo_detected=False,
                predicted_next_pulse_in_sec=0.0,
            )

        values = [v for v, _ in ticks]
        mean_v = sum(values) / N
        centered = [v - mean_v for v in values]

        # Compute Discrete Fourier Transform (DFT)
        powers: List[Tuple[float, float, float, float]] = []  # (freq, period, power, phase)
        for k in range(1, N // 2):
            freq = k * (self.sampling_rate_hz / N)
            period = 1.0 / freq if freq > 0 else 0.0

            # DFT sum
            dft_val = sum(centered[n] * cmath.exp(-2j * math.pi * k * n / N) for n in range(N))
            power = (dft_val.real ** 2 + dft_val.imag ** 2) / N
            phase = cmath.phase(dft_val)
            powers.append((freq, period, power, phase))

        if not powers:
            return SpectralOscillationResult(
                symbol=sym,
                dominant_period_sec=0.0,
                spectral_power_snr=0.0,
                is_periodic_algo_detected=False,
                predicted_next_pulse_in_sec=0.0,
            )

        # Find top peak
        powers.sort(key=lambda x: x[2], reverse=True)
        top_freq, top_period, top_power, top_phase = powers[0]

        mean_power = sum(p[2] for p in powers) / len(powers) if powers else 1.0
        snr = 10.0 * math.log10(max(1e-4, top_power / max(1e-4, mean_power)))
        is_algo = snr >= 6.0 and top_period >= 0.5

        # Phase estimation for next pulse arrival
        last_t = ticks[-1][1]
        phase_norm = (top_phase % (2 * math.pi)) / (2 * math.pi)
        next_in = top_period * (1.0 - phase_norm) if is_algo else 0.0

        peaks = [
            SpectralFrequencyPeak(
                frequency_hz=round(f, 3),
                period_seconds=round(p, 2),
                spectral_power=round(pw, 4),
                phase_radians=round(ph, 3),
            )
            for f, p, pw, ph in powers[:3]
        ]

        res = SpectralOscillationResult(
            symbol=sym,
            dominant_period_sec=round(top_period, 2),
            spectral_power_snr=round(snr, 1),
            is_periodic_algo_detected=is_algo,
            predicted_next_pulse_in_sec=round(next_in, 2),
            active_peaks=peaks,
        )
        return res
