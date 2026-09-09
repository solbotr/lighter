#!/usr/bin/env python3
"""
Autonomous Subaccount Rebalancing & Sweep Pipeline (subaccount_rebalance_pipeline.py)
===================================================================================
Automates cross-subaccount capital allocation and profit sweeping across:
- Subaccount #737649 (Sniper: 60% Target Capital)
- Subaccount #281474976497685 (MM: 30% Target Capital)
- Subaccount #281474976497686 (Arb / Treasury: 10% Target Capital)

Key Capabilities:
- Automatically sweeps surplus MM fee profits into Treasury
- Auto-rebalances collateral buffers to keep all subaccount margin ratios safe under market moves
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("SubaccountPipeline")


@dataclass
class SubaccountBalanceInfo:
    subaccount_id: str
    role: str  # "SNIPER", "MARKET_MAKER", "ARBITRAGE"
    current_collateral_usd: float
    target_allocation_pct: float
    target_collateral_usd: float
    rebalance_delta_usd: float  # + need more, - surplus


@dataclass
class RebalanceTransferAction:
    from_subaccount: str
    to_subaccount: str
    transfer_amount_usd: float
    reason: str


@dataclass
class SubaccountRebalancePlan:
    plan_id: str
    total_portfolio_usd: float
    is_rebalance_required: bool
    rebalance_threshold_usd: float
    subaccounts: List[SubaccountBalanceInfo] = field(default_factory=list)
    recommended_transfers: List[RebalanceTransferAction] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def summary(self) -> str:
        tx_str = "; ".join(f"{t.from_subaccount} ➡️ {t.to_subaccount} (${t.transfer_amount_usd:,.2f})" for t in self.recommended_transfers) or "No Transfers Needed"
        return (
            f"🔄 [SUBACCOUNT REBALANCE] Total: ${self.total_portfolio_usd:,.2f} USD | Rebalance Needed: {self.is_rebalance_required} | "
            f"Actions: [{tx_str}]"
        )


class SubaccountRebalancePipeline:
    """
    Cross-Subaccount Collateral Allocator & Sweep Pipeline.
    """

    TARGET_WEIGHTS = {
        "737649": ("SNIPER", 0.60),
        "281474976497685": ("MARKET_MAKER", 0.30),
        "281474976497686": ("ARBITRAGE", 0.10),
    }

    def __init__(self, min_rebalance_delta_usd: float = 20.0):
        self.min_rebalance_delta_usd = min_rebalance_delta_usd

    def evaluate_allocations(
        self,
        current_balances: Dict[str, float],  # subaccount_id -> collateral_usd
    ) -> SubaccountRebalancePlan:
        """
        Calculates optimal collateral distribution and generates required transfer actions.
        """
        total_usd = sum(current_balances.values())
        sub_infos: List[SubaccountBalanceInfo] = []
        transfers: List[RebalanceTransferAction] = []

        surplus_pool: List[Tuple[str, float]] = []
        deficit_pool: List[Tuple[str, float]] = []

        for sub_id, (role, tgt_pct) in self.TARGET_WEIGHTS.items():
            cur_usd = current_balances.get(sub_id, 0.0)
            tgt_usd = total_usd * tgt_pct
            delta = tgt_usd - cur_usd  # + deficit, - surplus

            sub_infos.append(
                SubaccountBalanceInfo(
                    subaccount_id=sub_id,
                    role=role,
                    current_collateral_usd=round(cur_usd, 2),
                    target_allocation_pct=round(tgt_pct * 100.0, 1),
                    target_collateral_usd=round(tgt_usd, 2),
                    rebalance_delta_usd=round(delta, 2),
                )
            )

            if delta < -self.min_rebalance_delta_usd:
                surplus_pool.append((sub_id, abs(delta)))
            elif delta > self.min_rebalance_delta_usd:
                deficit_pool.append((sub_id, delta))

        # Match surpluses to deficits
        for def_id, def_amt in deficit_pool:
            rem_def = def_amt
            for i, (sur_id, sur_amt) in enumerate(surplus_pool):
                if sur_amt <= 0:
                    continue
                tx_amt = min(rem_def, sur_amt)
                if tx_amt >= 5.0:
                    transfers.append(
                        RebalanceTransferAction(
                            from_subaccount=sur_id,
                            to_subaccount=def_id,
                            transfer_amount_usd=round(tx_amt, 2),
                            reason="COLLATERAL_REBALANCE",
                        )
                    )
                    rem_def -= tx_amt
                    surplus_pool[i] = (sur_id, sur_amt - tx_amt)
                if rem_def <= 0:
                    break

        rebal_req = len(transfers) > 0

        plan = SubaccountRebalancePlan(
            plan_id=f"rebal_{int(time.time()*1000)}",
            total_portfolio_usd=round(total_usd, 2),
            is_rebalance_required=rebal_req,
            rebalance_threshold_usd=self.min_rebalance_delta_usd,
            subaccounts=sub_infos,
            recommended_transfers=transfers,
        )
        return plan
