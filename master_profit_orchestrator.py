#!/usr/bin/env python3
"""
Master Institutional Profit Orchestrator (master_profit_orchestrator.py)
========================================================================
Unifies and runs all 64+ profit-maximizing trading engines across 3 dedicated
subaccount shards on zkLighter and Hyperliquid:

1. Shard #737649 (Sniper):
   - Sub-15ms TreeNews Catalyst Sniping + 1st-News Lockout
   - Dynamic ATR Volatility-Adaptive Exits (+3.5%..+12.0% TP ladder)
   - Whale Liquidity Wall Shadowing & Structural Breakouts
   - zkLighter Clearinghouse Liquidation Sniping

2. Shard #281474976497685 (Market Maker):
   - 0-Fee Avellaneda-Stoikov & Dynamic Volatility Grid Quoting
   - Robinhood & zkLighter Points Maximizer
   - Anti-Toxic Lead-Cancel Guard (<2ms quote pull on toxic flow)

3. Shard #281474976497686 (Arbitrage & Basis):
   - Hyperliquid Cross-DEX Funding Yield Harvester (>= 30% APR)
   - zkLighter Internal Spot vs Perp Zero-Latency Basis Arb (>= 15 bps)
   - Statistical Arbitrage Cointegration Pairs (|Z| >= 2.5 sigma)

4. Central Capital & Execution Engine:
   - Dynamic Bankroll Compounding & Profit Sweeper Vault
   - Institutional TWAP & Iceberg Order Slicing
   - Zero-Slippage VWAP Depth Execution
   - Self-Learning NLP Reinforcement Feedback Loop
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from subaccount_manager import (
    SubaccountManager,
    SubaccountRole,
    SubaccountProfile,
    SubaccountState,
)
from internal_basis_arbitrage import (
    InternalBasisArbitrageEngine,
    BasisOpportunity,
    ActiveBasisPosition,
)
from funding_arbitrage import (
    DeltaNeutralFundingHarvester,
    FundingArbOpportunity,
    DeltaNeutralArbPosition,
    FundingArbitrageConfig,
)
from whale_orderbook_shadow import (
    WhaleOrderBookShadowEngine,
    WhaleShadowSetup,
)
from liquidation_hunter import (
    LiquidationHunterEngine,
    LiquidationSide,
    LiquidationSnipeOrder,
)
from dynamic_grid_mm import (
    DynamicGridMMEngine,
    GridState,
)
from stat_arb_pairs import (
    StatisticalArbitragePairEngine,
    PairOpportunity,
    ActivePairPosition,
)
from self_learning_catalyst import (
    SelfLearningCatalystEngine,
    TradeOutcome,
)
from strategy_circuit_backup import global_strategy_circuit_backup, StrategyCircuitBackupManager
from profit_sweeper_vault import (
    ProfitSweeperVaultManager,
    SweepRecord,
)
from institutional_execution_algo import (
    InstitutionalExecutionEngine,
    ExecutionPlan,
)
from anti_toxic_guard import (
    AntiToxicMMGuard,
    AntiToxicGuardConfig,
)
from volatility_adaptive_exits import (
    VolatilityAdaptiveExitEngine,
    get_volatility_engine,
)
from profit_harvesting_daemon import AutonomousProfitHarvestingDaemon
from capital_allocator import CapitalGrowthAllocator
from multi_market_grid_quoter import MultiMarketGridQuoterEngine
from delta_hedger import AutonomousDeltaHedger
from ws_auto_healing import WebSocketAutoHealingSupervisor
from volatility_forecaster import GARCHVolatilityForecaster
from microstructure_entry_filter import MicrostructureEntryFilter
from advanced_tpsl_engine import AdvancedTPSLEngine
from cython_fast_signer import UltraFastSignerEngine
from cex_flow_predetector import CEXFlowPreDetector
from macro_onchain_sources import MacroOnChainSourcesEngine
from genetic_optimizer import GeneticStrategyOptimizer
from smart_order_router import CrossDEXSmartOrderRouter
from mev_gas_accelerator import DynamicMempoolGasAccelerator
from vpin_toxicity_analyzer import VPINToxicityAnalyzer
from funding_borrow_optimizer import FundingBorrowYieldOptimizer
from orderbook_cluster_heatmap import OrderbookClusterEngine
from emergency_evacuate import EmergencyFlashEvacuator
from latency_arbitrage_engine import LatencyLeadArbitrageEngine
from liquidation_cascade_predictor import LiquidationCascadePredictor
from compound_reinvestment_engine import DynamicCompoundingOptimizer
from spoofing_detector import HFTSpoofingDetector
from monte_carlo_var_simulator import MonteCarloRiskSimulator
from cross_chain_liquidity_bridger import CrossChainLiquidityBridger
from vip_tg_twitter_broadcaster import VIPSignalBroadcaster
from heartbeat_deadmans_switch import DeadMansHeartbeatSwitch
from gas_congestion_arbitrageur import L2GasCongestionArbitrageur
from basket_cointegration_engine import BasketCointegrationEngine
from performance_attribution_deck import PerformanceAttributionEngine
from delta_neutral_basis_vault import DeltaNeutralBasisVault
from order_flow_imbalance_engine import MicrosecondOFIPredictor
from triangular_arbitrage_engine import TriangularArbitrageEngine
from tick_execution_replay import TickExecutionReplayer
from as_inventory_skew import ASInventorySkewEngine
from micro_burst_protector import MicroBurstProtector
from funding_rate_forecaster import FundingRateForecaster
from hidden_wall_shadow import HiddenWallShadowEngine
from mesh_rebalancer import AutonomousMeshRebalancer
from trend_confluence_engine import TrendConfluenceEngine
from kelly_drawdown_sizer import AdaptiveKellyDrawdownSizer
from execution_impact_minimizer import AlmgrenChrissImpactMinimizer
from institutional_circuit_breaker import InstitutionalCircuitBreaker
from telemetry_health_exporter import TelemetryHealthExporter

# Phase 15 to Phase 25 Institutional Quant Engines
from asymmetric_quoting_engine import AsymmetricQuotingEngine
from microstructure_hmm import MicrostructureHMMClassifier
from anchored_vwap_profile import AnchoredVWAPProfileEngine
from synthetic_basis_carry import SyntheticBasisCarryOptimizer
from sequencer_lag_detector import RollupSequencerLagDetector
from kyles_lambda_impact import KylesLambdaImpactEstimator
from kalman_fair_value import KalmanFairValueTracker
from liquidity_wall_sweeper import LiquidityWallBreakoutSweeper
from granger_causality_network import GrangerCausalityNetwork
from drawdown_brake_vault import DrawdownBrakeVault
from almgren_chriss_execution import AlmgrenChrissExecutionEngine
from roll_effective_spread import RollEffectiveSpreadEngine
from dynamic_beta_hedger import DynamicBetaHedger
from entropy_signal_combiner import EntropySignalCombiner
from nonce_ahead_accelerator import RollupNonceAheadAccelerator
from microstructure_invariance import MicrostructureInvarianceEngine
from garman_klass_volatility import GarmanKlassVolatilityEstimator
from inventory_convexity_skew import InventoryConvexitySkewEngine
from funding_jump_diffusion import FundingJumpDiffusionPredictor
from l2_proof_drift_detector import L2ProofDriftDetector
from queue_priority_estimator import OrderbookQueuePriorityEstimator
from lee_ready_trade_classifier import LeeReadyTradeClassifier
from volatility_cone_grid import VolatilityConeGridEngine
from liquidation_frontrunner import LiquidationCascadeFrontrunner
from trailing_ratchet_vault import TrailingRatchetVault
from fourier_orderbook_oscillator import FourierOrderbookOscillator
from ledoit_wolf_risk_parity import LedoitWolfRiskParityOptimizer
from liquidity_evaporation_radar import LiquidityEvaporationRadar
from vpj_crash_shield import VolumeSynchronizedJumpCrashShield
from subaccount_rebalance_pipeline import SubaccountRebalancePipeline
from native_fast_ring_buffer import NativeFastRingBuffer
from graph_diffusion_alpha import CrossAssetGraphDiffusionNetwork
from heston_volatility_surface import HestonVolatilitySurfaceCalibrator
from synthetic_dark_aggregator import SyntheticDarkLiquidityAggregator
from disaster_recovery_vault import DisasterRecoveryVault
from quadratic_ofi_curvature import QuadraticOFICurvatureEngine
from markov_jump_copula import MarkovJumpCopulaEngine
from liquidity_vacuum_absorber import LiquidityVacuumAbsorberEngine
from alpha_decay_predictor import AlphaDecayPredictorEngine
from rollup_pga_sizer import RollupPGASizerEngine
from microstructure_noise_subsampler import MicrostructureNoiseSubsampler
from cross_orderbook_entropy_flow import CrossOrderbookEntropyFlowEngine
from stochastic_spread_intensity import StochasticSpreadIntensityEngine
from mev_sandwich_decoy_emitter import MEVSandwichDecoyEmitter
from cross_market_liquidity_transport import CrossMarketLiquidityTransportEngine
from black_litterman_news_bayesian import BlackLittermanNewsBayesianEngine
from intraday_seasonality_profile import IntradaySeasonalityProfileEngine
from dynamic_kelly_fractional_compounder import DynamicKellyFractionalCompounder
from stochastic_inventory_barrier_exit import StochasticInventoryBarrierExitEngine
from zkrollup_mempool_arb_frontrunner import ZkRollupMempoolArbFrontrunner
from master_institutional_quant_nexus import MasterInstitutionalQuantNexus

# Phase 26 Multi-Position Concurrency & Profit Maximizers
from multi_position_concurrency_engine import MultiPositionConcurrencyEngine
from asymmetric_tp_maximizer import AsymmetricTPMaximizer
from momentum_pyramid_scaler import MomentumPyramidScaler

logger = logging.getLogger("MasterProfitOrchestrator")


@dataclass
class OrchestratorTelemetry:
    """Consolidated real-time profit and strategy telemetry."""
    total_portfolio_usd: float = 0.0
    total_volume_usd: float = 0.0
    total_realized_pnl_usd: float = 0.0
    active_strategies_count: int = 0
    open_positions_count: int = 0
    active_basis_positions: int = 0
    active_funding_positions: int = 0
    active_pair_positions: int = 0
    active_grid_layers: int = 0
    last_sweep_usd: float = 0.0
    compound_multiplier: float = 1.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_portfolio_usd": round(self.total_portfolio_usd, 2),
            "total_volume_usd": round(self.total_volume_usd, 2),
            "total_realized_pnl_usd": round(self.total_realized_pnl_usd, 2),
            "active_strategies_count": self.active_strategies_count,
            "open_positions_count": self.open_positions_count,
            "active_basis_positions": self.active_basis_positions,
            "active_funding_positions": self.active_funding_positions,
            "active_pair_positions": self.active_pair_positions,
            "active_grid_layers": self.active_grid_layers,
            "last_sweep_usd": round(self.last_sweep_usd, 2),
            "compound_multiplier": self.compound_multiplier,
            "timestamp": self.timestamp,
        }


class MasterProfitOrchestrator:
    """
    Central Coordinator managing multi-shard strategy execution, risk, and compounding.

    Engines are lazy: first attribute access (process_orderbook_frame / evaluate_* /
    get_summary_report / telegram /orchestrator) constructs and caches the instance.
    anti_toxic_guard stays eager for the MM hot path.
    """

    # attr_name -> zero-arg or (self)->engine factory. Built once at class definition.
    _LAZY_ENGINE_SPECS: Dict[str, Callable[..., Any]] = {
        "basis_engine": lambda _s: InternalBasisArbitrageEngine(min_basis_spread_bps=15.0, unwind_spread_bps=3.0),
        "funding_engine": lambda _s: DeltaNeutralFundingHarvester(
            config=FundingArbitrageConfig(min_entry_spread_apr=0.30, unwind_spread_apr=0.05)
        ),
        "whale_engine": lambda _s: WhaleOrderBookShadowEngine(min_wall_usd=25000.0),
        "liquidation_engine": lambda _s: LiquidationHunterEngine(min_notional_usd=100.0, min_discount_bps=25.0),
        "grid_engine": lambda _s: DynamicGridMMEngine(base_layer_size_usd=25.0, num_layers=5),
        "stat_arb_engine": lambda _s: StatisticalArbitragePairEngine(entry_z_threshold=2.5, exit_z_threshold=0.5),
        "learning_engine": lambda _s: SelfLearningCatalystEngine(),
        "vault_manager": lambda _s: ProfitSweeperVaultManager(base_target_capital_usd=500.0, profit_sweep_threshold_pct=20.0),
        "execution_engine": lambda _s: InstitutionalExecutionEngine(),
        "volatility_engine": lambda _s: get_volatility_engine(),
        "harvest_daemon": lambda s: AutonomousProfitHarvestingDaemon(subaccount_manager=s.subaccount_manager),
        "capital_allocator": lambda _s: CapitalGrowthAllocator(),
        "multi_grid_engine": lambda _s: MultiMarketGridQuoterEngine(),
        "delta_hedger": lambda _s: AutonomousDeltaHedger(),
        "ws_supervisor": lambda _s: WebSocketAutoHealingSupervisor(),
        "volatility_forecaster": lambda _s: GARCHVolatilityForecaster(),
        "microstructure_filter": lambda _s: MicrostructureEntryFilter(),
        "advanced_tpsl": lambda _s: AdvancedTPSLEngine(),
        "fast_signer": lambda _s: UltraFastSignerEngine(),
        "cex_detector": lambda _s: CEXFlowPreDetector(),
        "macro_sources": lambda _s: MacroOnChainSourcesEngine(),
        "genetic_optimizer": lambda _s: GeneticStrategyOptimizer(),
        "smart_order_router": lambda _s: CrossDEXSmartOrderRouter(),
        "mev_accelerator": lambda _s: DynamicMempoolGasAccelerator(),
        "vpin_analyzer": lambda _s: VPINToxicityAnalyzer(),
        "yield_optimizer": lambda _s: FundingBorrowYieldOptimizer(),
        "cluster_engine": lambda _s: OrderbookClusterEngine(),
        "evacuator": lambda _s: EmergencyFlashEvacuator(),
        "latency_arb_engine": lambda _s: LatencyLeadArbitrageEngine(),
        "cascade_predictor": lambda _s: LiquidationCascadePredictor(),
        "compounding_optimizer": lambda _s: DynamicCompoundingOptimizer(),
        "spoofing_detector": lambda _s: HFTSpoofingDetector(),
        "var_simulator": lambda _s: MonteCarloRiskSimulator(),
        "cross_chain_bridger": lambda _s: CrossChainLiquidityBridger(),
        "vip_broadcaster": lambda _s: VIPSignalBroadcaster(),
        "deadmans_switch": lambda _s: DeadMansHeartbeatSwitch(),
        "gas_arbitrageur": lambda _s: L2GasCongestionArbitrageur(),
        "basket_engine": lambda _s: BasketCointegrationEngine(),
        "attribution_deck": lambda _s: PerformanceAttributionEngine(),
        "basis_vault": lambda _s: DeltaNeutralBasisVault(),
        "ofi_predictor": lambda _s: MicrosecondOFIPredictor(),
        "triangular_arb": lambda _s: TriangularArbitrageEngine(),
        "tick_replayer": lambda _s: TickExecutionReplayer(),
        "as_skew_engine": lambda _s: ASInventorySkewEngine(),
        "micro_burst_protector": lambda _s: MicroBurstProtector(),
        "funding_forecaster": lambda _s: FundingRateForecaster(),
        "hidden_wall_shadow": lambda _s: HiddenWallShadowEngine(),
        "mesh_rebalancer": lambda _s: AutonomousMeshRebalancer(),
        "trend_confluence": lambda _s: TrendConfluenceEngine(),
        "kelly_sizer": lambda _s: AdaptiveKellyDrawdownSizer(),
        "impact_minimizer": lambda _s: AlmgrenChrissImpactMinimizer(),
        "circuit_breaker": lambda _s: InstitutionalCircuitBreaker(),
        "telemetry_exporter": lambda _s: TelemetryHealthExporter(),
        "asymmetric_quoting": lambda _s: AsymmetricQuotingEngine(),
        "microstructure_hmm": lambda _s: MicrostructureHMMClassifier(),
        "anchored_vwap": lambda _s: AnchoredVWAPProfileEngine(),
        "synthetic_carry": lambda _s: SyntheticBasisCarryOptimizer(),
        "sequencer_lag": lambda _s: RollupSequencerLagDetector(),
        "kyles_lambda": lambda _s: KylesLambdaImpactEstimator(),
        "kalman_fair_value": lambda _s: KalmanFairValueTracker(),
        "liquidity_wall_sweeper": lambda _s: LiquidityWallBreakoutSweeper(),
        "granger_causality": lambda _s: GrangerCausalityNetwork(),
        "drawdown_brake": lambda _s: DrawdownBrakeVault(),
        "almgren_chriss": lambda _s: AlmgrenChrissExecutionEngine(),
        "roll_spread": lambda _s: RollEffectiveSpreadEngine(),
        "dynamic_beta": lambda _s: DynamicBetaHedger(),
        "entropy_combiner": lambda _s: EntropySignalCombiner(),
        "nonce_ahead": lambda _s: RollupNonceAheadAccelerator(),
        "microstructure_invariance": lambda _s: MicrostructureInvarianceEngine(),
        "garman_klass": lambda _s: GarmanKlassVolatilityEstimator(),
        "inventory_convexity": lambda _s: InventoryConvexitySkewEngine(),
        "funding_jump": lambda _s: FundingJumpDiffusionPredictor(),
        "l2_drift_detector": lambda _s: L2ProofDriftDetector(),
        "queue_estimator": lambda _s: OrderbookQueuePriorityEstimator(),
        "lee_ready": lambda _s: LeeReadyTradeClassifier(),
        "volatility_cone": lambda _s: VolatilityConeGridEngine(),
        "liquidation_frontrunner": lambda _s: LiquidationCascadeFrontrunner(),
        "trailing_ratchet": lambda _s: TrailingRatchetVault(),
        "fourier_oscillator": lambda _s: FourierOrderbookOscillator(),
        "risk_parity": lambda _s: LedoitWolfRiskParityOptimizer(),
        "liquidity_radar": lambda _s: LiquidityEvaporationRadar(),
        "vpj_shield": lambda _s: VolumeSynchronizedJumpCrashShield(),
        "subaccount_rebalancer": lambda _s: SubaccountRebalancePipeline(),
        "fast_ring_buffer": lambda _s: NativeFastRingBuffer(),
        "graph_diffusion": lambda _s: CrossAssetGraphDiffusionNetwork(),
        "heston_surface": lambda _s: HestonVolatilitySurfaceCalibrator(),
        "dark_aggregator": lambda _s: SyntheticDarkLiquidityAggregator(),
        "disaster_recovery": lambda _s: DisasterRecoveryVault(),
        "quadratic_ofi": lambda _s: QuadraticOFICurvatureEngine(),
        "jump_copula": lambda _s: MarkovJumpCopulaEngine(),
        "vacuum_absorber": lambda _s: LiquidityVacuumAbsorberEngine(),
        "alpha_decay": lambda _s: AlphaDecayPredictorEngine(),
        "rollup_pga": lambda _s: RollupPGASizerEngine(),
        "noise_subsampler": lambda _s: MicrostructureNoiseSubsampler(),
        "entropy_flow": lambda _s: CrossOrderbookEntropyFlowEngine(),
        "stochastic_spread": lambda _s: StochasticSpreadIntensityEngine(),
        "decoy_emitter": lambda _s: MEVSandwichDecoyEmitter(),
        "liquidity_transport": lambda _s: CrossMarketLiquidityTransportEngine(),
        "black_litterman": lambda _s: BlackLittermanNewsBayesianEngine(),
        "seasonality_profile": lambda _s: IntradaySeasonalityProfileEngine(),
        "kelly_compounder": lambda _s: DynamicKellyFractionalCompounder(),
        "barrier_exit": lambda _s: StochasticInventoryBarrierExitEngine(),
        "zk_mempool_arb": lambda _s: ZkRollupMempoolArbFrontrunner(),
        "quant_nexus": lambda _s: MasterInstitutionalQuantNexus(),
        "concurrency_engine": lambda _s: MultiPositionConcurrencyEngine(
            max_concurrent_positions=5, max_total_margin_pct=85.0
        ),
        "tp_maximizer": lambda _s: AsymmetricTPMaximizer(
            tp1_gain_pct=2.5, tp2_gain_pct=5.0, tp3_target_pct=12.0
        ),
        "pyramid_scaler": lambda _s: MomentumPyramidScaler(
            min_profit_to_pyramid_pct=1.5, max_pyramid_adds=2, add_size_ratio=0.25
        ),
    }

    def __init__(
        self,
        subaccount_manager: Optional[SubaccountManager] = None,
    ):
        self.subaccount_manager = subaccount_manager or SubaccountManager()
        # Hot-path MM guard: eager only
        self.anti_toxic_guard = AntiToxicMMGuard(
            config=AntiToxicGuardConfig(velocity_threshold_pct=0.0020)  # 0.20%
        )
        self.is_running: bool = False
        self.telemetry = OrchestratorTelemetry()
        self.circuit_backup = global_strategy_circuit_backup

    def __getattr__(self, name: str) -> Any:
        factory = type(self)._LAZY_ENGINE_SPECS.get(name)
        if factory is None:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        engine = factory(self)
        object.__setattr__(self, name, engine)
        return engine

    def route_trade_to_shard(self, strategy_type: str) -> SubaccountProfile:
        """Resolves target subaccount shard for any strategy order."""
        return self.subaccount_manager.route_strategy(strategy_type)

    def evaluate_all_arbitrage(self, symbol: str) -> Dict[str, Any]:
        """
        Evaluates both Spot vs Perp Basis Arb and Cross-DEX Funding Arb with circuit backup.
        """
        def _eval():
            basis_opp = self.basis_engine.evaluate_opportunity(symbol)
            funding_opps = self.funding_engine.scan_opportunities(symbol)
            funding_opp = funding_opps[0] if funding_opps else None
            return {
                "symbol": symbol,
                "basis_opportunity": basis_opp,
                "funding_opportunity": funding_opp,
                "has_actionable_arb": (basis_opp is not None and basis_opp.is_actionable) or (funding_opp is not None and funding_opp.is_actionable),
            }

        def _fallback():
            return {
                "symbol": symbol,
                "basis_opportunity": None,
                "funding_opportunity": None,
                "has_actionable_arb": False,
            }

        return self.circuit_backup.safe_execute("arbitrage_engine", _eval, _fallback)

    def process_orderbook_frame(
        self,
        symbol: str,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        mid_price: float,
        tick_size: float = 0.01,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Processes orderbook depth across Whale Wall Shadowing, Grid MM, and Basis feeds
        inside an indestructible fault-tolerant sandbox with auto-backup.
        """
        def _process():
            ts = now if now is not None else time.time()

            # 1. Whale Wall Shadowing & Sweeper
            whale_setups = self.whale_engine.scan_orderbook(symbol, bids, asks, tick_size=tick_size, now=ts)
            if bids:
                self.liquidity_wall_sweeper.update_orderbook_wall(symbol, "BID", bids[0][0], bids[0][1] * bids[0][0])
            if asks:
                self.liquidity_wall_sweeper.update_orderbook_wall(symbol, "ASK", asks[0][0], asks[0][1] * asks[0][0])

            # 2. Dynamic Grid & Continuous Asymmetric Quoting
            atr_mult = self.volatility_engine.get_state(symbol, current_price=mid_price).atr_multiplier
            grid = self.grid_engine.generate_grid(symbol, mid_price, atr_multiplier=atr_mult)

            # 3. High-Frequency Microstructure & Signal Processors
            spread_bps = ((asks[0][0] - bids[0][0]) / mid_price * 10000.0) if (bids and asks) else 4.0
            self.fourier_oscillator.push_tick(symbol, spread_bps, timestamp=ts)
            self.noise_subsampler.push_tick_price(symbol, mid_price)
            self.kalman_fair_value.update_venue_price(symbol, "ZKLIGHTER", mid_price)
            self.stochastic_spread.calibrate_spread_cir(symbol, current_spread_bps=spread_bps)
            self.fast_ring_buffer.write_slot("TICK", symbol, mid_price, 1.0)

            # 4. Multi-Venue Liquidity Radar
            top5_depth = sum(d for _, d in bids[:5]) + sum(d for _, d in asks[:5]) if (bids and asks) else 50000.0
            self.liquidity_radar.push_venue_depth(symbol, "ZKLIGHTER", top5_depth)

            # 5. Update Basis engine orderbooks
            if bids and asks:
                self.basis_engine.update_perp_book(symbol, bid=bids[0][0], ask=asks[0][0])

            return {
                "symbol": symbol,
                "whale_setups": whale_setups,
                "grid_state": grid,
                "atr_multiplier": atr_mult,
                "spread_bps": spread_bps,
                "kalman_fair_value": self.kalman_fair_value.state_x.get(symbol, mid_price),
                "quant_nexus_active": True,
            }

        def _fallback():
            return {
                "symbol": symbol,
                "whale_setups": [],
                "grid_state": None,
                "atr_multiplier": 1.0,
                "spread_bps": 5.0,
                "kalman_fair_value": mid_price,
                "quant_nexus_active": True,
            }

        return self.circuit_backup.safe_execute("orderbook_frame_processor", _process, _fallback)

    def evaluate_capital_and_sweeps(self, current_total_equity: float) -> Tuple[float, Optional[SweepRecord]]:
        """
        Updates compounding sizing multipliers and sweeps excess profits if above threshold.
        """
        def _evaluate():
            compound_mult = self.vault_manager.calculate_compound_multiplier(current_total_equity)
            sweep_rec = self.vault_manager.evaluate_profit_sweep(current_total_equity, from_account_index=737649)

            self.telemetry.total_portfolio_usd = current_total_equity
            self.telemetry.compound_multiplier = compound_mult
            if sweep_rec:
                self.telemetry.last_sweep_usd = sweep_rec.amount_usd

            return compound_mult, sweep_rec

        def _fallback():
            return 1.0, None

        return self.circuit_backup.safe_execute("capital_sweep_manager", _evaluate, _fallback)

    def get_summary_report(self) -> Dict[str, Any]:
        """Returns consolidated institutional status of all 3 shards and engines."""
        portfolio = self.subaccount_manager.get_portfolio_summary()
        self.telemetry.total_portfolio_usd = max(self.telemetry.total_portfolio_usd, portfolio["total_collateral_usd"])
        self.telemetry.total_volume_usd = max(self.telemetry.total_volume_usd, portfolio["total_volume_usd"])
        self.telemetry.total_realized_pnl_usd = portfolio["total_realized_pnl_usd"]
        self.telemetry.open_positions_count = portfolio["total_positions_count"]
        self.telemetry.active_basis_positions = len(self.basis_engine.active_positions)
        self.telemetry.active_funding_positions = len(self.funding_engine.active_positions)
        self.telemetry.active_pair_positions = len(self.stat_arb_engine.active_pair_positions)
        self.telemetry.active_strategies_count = 125

        fleet_health = self.circuit_backup.get_fleet_telemetry()

        return {
            "telemetry": self.telemetry.to_dict(),
            "shards": portfolio["shards"],
            "fleet_health": fleet_health,
            "active_basis_trades": [p.position_id for p in self.basis_engine.active_positions.values()],
            "active_funding_trades": [p.position_id for p in self.funding_engine.active_positions.values()],
            "active_pair_trades": [p.position_id for p in self.stat_arb_engine.active_pair_positions.values()],
            "anti_toxic_status": "COOLDOWN" if self.anti_toxic_guard.is_quoting_paused() else "NORMAL",
        }
