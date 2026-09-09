#!/usr/bin/env python3
"""
Master Institutional Quant Nexus (master_institutional_quant_nexus.py)
======================================================================
Telemetry aggregator for quant modules. Reports only values the caller
supplies (portfolio, engine census, health, Sharpe, volume). Unmeasured
fields stay 0 / UNKNOWN instead of invented headlines.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

logger = logging.getLogger("QuantNexus")


@dataclass
class NexusSystemTelemetry:
    active_quant_engines_count: int
    total_pipeline_latency_us: float  # Microseconds
    nexus_state: str  # UNKNOWN / CONFIGURED until real health is supplied
    active_subaccounts_count: int
    total_portfolio_usd: float
    daily_sharpe_ratio: float
    total_volume_farmed_usd: float
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        return (
            f"🏛️ [MASTER QUANT NEXUS] State: {self.nexus_state} | Active Engines: {self.active_quant_engines_count} | "
            f"Pipeline Latency: {self.total_pipeline_latency_us:.1f}μs | Capital: ${self.total_portfolio_usd:,.2f} USD | "
            f"Daily Sharpe: {self.daily_sharpe_ratio:.2f} | Volume Farmed: ${self.total_volume_farmed_usd:,.2f} USD"
        )


class MasterInstitutionalQuantNexus:
    """
    Unified Master Nexus Coordinator.
    Defaults are honest zeros / UNKNOWN. Callers may inject live values.
    """

    def __init__(
        self,
        portfolio_usd: float = 0.0,
        active_engines: Optional[int] = None,
        engine_registry: Optional[Sequence[Any]] = None,
        nexus_state: Optional[str] = None,
        daily_sharpe_ratio: float = 0.0,
        total_volume_farmed_usd: float = 0.0,
        total_pipeline_latency_us: float = 0.0,
        active_subaccounts_count: int = 0,
        health: Optional[str] = None,
    ):
        self.portfolio_usd = float(portfolio_usd)
        self._active_engines = active_engines
        self._engine_registry = engine_registry
        self._nexus_state = nexus_state
        self._health = health
        self.daily_sharpe_ratio = float(daily_sharpe_ratio)
        self.total_volume_farmed_usd = float(total_volume_farmed_usd)
        self.total_pipeline_latency_us = float(total_pipeline_latency_us)
        self.active_subaccounts_count = int(active_subaccounts_count)

    def _resolve_engine_count(
        self,
        active_engines: Optional[int] = None,
        engine_registry: Optional[Sequence[Any]] = None,
    ) -> int:
        if active_engines is not None:
            return int(active_engines)
        if self._active_engines is not None:
            return int(self._active_engines)
        registry = engine_registry if engine_registry is not None else self._engine_registry
        if registry is not None:
            try:
                return len(registry)
            except TypeError:
                return 0
        return 0

    def _resolve_nexus_state(
        self,
        *,
        nexus_state: Optional[str] = None,
        health: Optional[str] = None,
        active_engines: Optional[int] = None,
        engine_registry: Optional[Sequence[Any]] = None,
    ) -> str:
        supplied = health if health is not None else nexus_state
        if supplied is None:
            supplied = self._health if self._health is not None else self._nexus_state
        if supplied is not None:
            return supplied
        configured = (
            active_engines is not None
            or self._active_engines is not None
            or engine_registry is not None
            or self._engine_registry is not None
        )
        if configured:
            return "CONFIGURED"
        return "UNKNOWN"

    def get_system_telemetry(
        self,
        *,
        active_engines: Optional[int] = None,
        engine_registry: Optional[Sequence[Any]] = None,
        nexus_state: Optional[str] = None,
        daily_sharpe_ratio: Optional[float] = None,
        total_volume_farmed_usd: Optional[float] = None,
        total_pipeline_latency_us: Optional[float] = None,
        active_subaccounts_count: Optional[int] = None,
        health: Optional[str] = None,
        portfolio_usd: Optional[float] = None,
    ) -> NexusSystemTelemetry:
        """
        Snapshot of supplied telemetry. Unpassed fields keep constructor
        defaults (0 / UNKNOWN), not decorative placeholders.
        """
        engine_count = self._resolve_engine_count(active_engines, engine_registry)
        return NexusSystemTelemetry(
            active_quant_engines_count=engine_count,
            total_pipeline_latency_us=(
                float(total_pipeline_latency_us)
                if total_pipeline_latency_us is not None
                else self.total_pipeline_latency_us
            ),
            nexus_state=self._resolve_nexus_state(
                nexus_state=nexus_state,
                health=health,
                active_engines=active_engines,
                engine_registry=engine_registry,
            ),
            active_subaccounts_count=(
                int(active_subaccounts_count)
                if active_subaccounts_count is not None
                else self.active_subaccounts_count
            ),
            total_portfolio_usd=(
                float(portfolio_usd) if portfolio_usd is not None else self.portfolio_usd
            ),
            daily_sharpe_ratio=(
                float(daily_sharpe_ratio)
                if daily_sharpe_ratio is not None
                else self.daily_sharpe_ratio
            ),
            total_volume_farmed_usd=(
                float(total_volume_farmed_usd)
                if total_volume_farmed_usd is not None
                else self.total_volume_farmed_usd
            ),
        )
