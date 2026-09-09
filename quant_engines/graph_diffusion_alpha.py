#!/usr/bin/env python3
"""
Cross-Asset Graph Diffusion Alpha Network (graph_diffusion_alpha.py)
===================================================================
Models the crypto asset ecosystem as a weighted directed knowledge graph:
  Graph Diffusion: H^{(t+1)} = (1 - α) · A_norm · H^{(t)} + α · S_catalyst

Sectors / Clusters:
- AI & Compute: NEAR, RENDER, FET, TAO, AKT
- Solana Ecosystem: SOL, JUP, RAY, PYTH, BONK, JTO
- L1/L2 Infrastructure: ETH, OP, ARB, STRK, MATIC
- Memes & Beta: DOGE, SHIB, PEPE, WIF, FLOKI

Key Capabilities:
- When a breaking catalyst hits a primary node (e.g. OpenAI news -> AI cluster),
  the network propagates momentum energy across all connected edges to pre-emptively
  snipe 2nd-order follower tokens before retail discovers the narrative link.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("GraphDiffusion")


@dataclass
class PropagatedAssetAlpha:
    symbol: str
    sector: str
    direct_catalyst_source: str
    diffusion_conviction_score: float  # 0.0 to 100.0
    recommended_direction: str  # "BUY", "SELL", "HOLD"
    estimated_lag_window_sec: float
    hop_distance: int


@dataclass
class GraphDiffusionCascadeResult:
    cascade_id: str
    primary_catalyst_asset: str
    primary_sector: str
    sentiment_direction: str
    diffused_assets_count: int
    top_propagated_alphas: List[PropagatedAssetAlpha] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        targets_str = ", ".join(f"{a.symbol} ({a.recommended_direction} {a.diffusion_conviction_score:.1f}%)" for a in self.top_propagated_alphas[:4])
        return (
            f"🕸️ [GRAPH DIFFUSION] Catalyst on {self.primary_catalyst_asset} ({self.primary_sector}, {self.sentiment_direction}) ➡️ "
            f"Diffused {self.diffused_assets_count} Ecosystem Nodes: [{targets_str}]"
        )


class CrossAssetGraphDiffusionNetwork:
    """
    Graph Laplacian Sector Momentum Diffusion Engine.
    """

    GRAPH_EDGES: Dict[str, Dict[str, float]] = {
        # AI Cluster
        "NEAR": {"RENDER": 0.85, "FET": 0.80, "TAO": 0.75},
        "RENDER": {"NEAR": 0.85, "FET": 0.82, "TAO": 0.78},
        "FET": {"NEAR": 0.80, "RENDER": 0.82, "TAO": 0.76},
        # Solana Ecosystem
        "SOL": {"JUP": 0.90, "RAY": 0.88, "PYTH": 0.85, "HYPE": 0.78, "BONK": 0.75},
        "HYPE": {"SOL": 0.78, "JUP": 0.75},
        # L1/L2
        "ETH": {"OP": 0.85, "ARB": 0.82, "STRK": 0.78},
        # Memes
        "DOGE": {"SHIB": 0.80, "PEPE": 0.75, "WIF": 0.70},
    }

    SECTOR_MAP: Dict[str, str] = {
        "NEAR": "AI", "RENDER": "AI", "FET": "AI", "TAO": "AI",
        "SOL": "SOLANA", "JUP": "SOLANA", "RAY": "SOLANA", "PYTH": "SOLANA", "HYPE": "SOLANA", "BONK": "SOLANA",
        "ETH": "L1_L2", "OP": "L1_L2", "ARB": "L1_L2", "STRK": "L1_L2",
        "DOGE": "MEMES", "SHIB": "MEMES", "PEPE": "MEMES", "WIF": "MEMES",
    }

    def __init__(self, diffusion_alpha: float = 0.35, min_diffusion_threshold: float = 60.0):
        self.diffusion_alpha = diffusion_alpha
        self.min_diffusion_threshold = min_diffusion_threshold

    def propagate_catalyst(
        self,
        primary_asset: str,
        direction: str,
        catalyst_conviction_score: float = 95.0,
    ) -> GraphDiffusionCascadeResult:
        """
        Diffuses catalyst momentum across graph edges to find 2nd-order breakout candidates.
        """
        sym = primary_asset.upper()
        dir_str = direction.upper()
        sector = self.SECTOR_MAP.get(sym, "GENERAL")

        connected = self.GRAPH_EDGES.get(sym, {})
        propagated: List[PropagatedAssetAlpha] = []

        for target_sym, edge_weight in connected.items():
            # Diffused conviction = Base Conviction * Edge Weight * (1 - alpha)
            diff_score = catalyst_conviction_score * edge_weight * (1.0 + self.diffusion_alpha * 0.5)
            diff_score = max(10.0, min(99.0, diff_score))

            if diff_score >= self.min_diffusion_threshold:
                # Follower lag estimate = (1.0 - edge_weight) * 3.0s + 0.5s
                lag_sec = (1.0 - edge_weight) * 3.0 + 0.5

                propagated.append(
                    PropagatedAssetAlpha(
                        symbol=target_sym,
                        sector=self.SECTOR_MAP.get(target_sym, "GENERAL"),
                        direct_catalyst_source=sym,
                        diffusion_conviction_score=round(diff_score, 1),
                        recommended_direction=dir_str,
                        estimated_lag_window_sec=round(lag_sec, 2),
                        hop_distance=1,
                    )
                )

        propagated.sort(key=lambda x: x.diffusion_conviction_score, reverse=True)

        res = GraphDiffusionCascadeResult(
            cascade_id=f"diff_{sym}_{int(time.time()*1000)}",
            primary_catalyst_asset=sym,
            primary_sector=sector,
            sentiment_direction=dir_str,
            diffused_assets_count=len(propagated),
            top_propagated_alphas=propagated,
        )
        return res
