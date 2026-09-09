#!/usr/bin/env python3
"""
B20 Bot Monitor Service - Auto-Run with Event Monitoring
=========================================================
Continuously monitors for B20 pools and automatically triggers buys
Runs 24/7 and triggers bot execution whenever a new pool is detected
"""

import os
import sys
import time
import threading
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Callable, Optional

from web3 import Web3
from eth_utils import to_checksum_address
from dotenv import load_dotenv

# Import our modules
from db_manager import DBManager
from safety_analyzer import SafetyAnalyzer
from event_monitor import EventMonitor
from risk_manager import RiskManager
from execution_engine import ExecutionEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/ubuntu/b20-bot/logs/monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class B20Monitor:
    """24/7 monitor that auto-runs bot when pools detected."""

    # Mainnet addresses
    CHAIN_ID = 8453
    ACTIVATION_REGISTRY = to_checksum_address("0x8453000000000000000000000000000000000001")
    B20_FACTORY = to_checksum_address("0xB20f000000000000000000000000000000000000")
    UNISWAP_V3_FACTORY = to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")
    UNISWAP_V3_ROUTER = to_checksum_address("0xE592427A0AEce92De3Edee1F18E0157C05861564")
    UNISWAP_QUOTER_V2 = to_checksum_address("0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a")
    WETH = to_checksum_address("0x4200000000000000000000000000000000000006")

    def __init__(self, config: Dict):
        self.config = config
        self.db = None
        self.risk_mgr = None
        self.w3 = None
        self.event_monitor = None
        self.safety_analyzer = None
        self.execution_engine = None
        
        self.is_running = True
        self.processed_pools = set()
        self.pending_pools = []
        self.lock = threading.Lock()

    def initialize(self):
        """Initialize all components."""
        logger.info("🚀 Initializing B20 Monitor...")
        
        # Connect to RPC
        rpc_url = self.config.get('RPC_URL')
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        if not self.w3.is_connected():
            logger.error(f"❌ Cannot connect to {rpc_url}")
            raise Exception("RPC connection failed")
        
        logger.info(f"✅ Connected to RPC: {rpc_url[:50]}...")
        
        # Initialize components
        self.db = DBManager(db_path="/home/ubuntu/b20-bot/data/b20_bot.db")
        self.risk_mgr = RiskManager(
            max_position_eth=self.config.get('MAX_TRADE_ETH', 0.1),
            daily_loss_limit_eth=self.config.get('MAX_DAILY_LOSS_ETH', 0.5)
        )
        self.safety_analyzer = SafetyAnalyzer(
            self.w3,
            self.UNISWAP_QUOTER_V2,
            self.UNISWAP_V3_ROUTER,
            self.WETH
        )
        self.event_monitor = EventMonitor(
            self.w3,
            self.B20_FACTORY,
            self.UNISWAP_V3_FACTORY,
            self.WETH
        )
        self.execution_engine = ExecutionEngine(
            self.w3,
            self.UNISWAP_QUOTER_V2,
            self.UNISWAP_V3_ROUTER,
            self.WETH,
            private_key=self.config.get('PRIVATE_KEY', ''),
            use_flashbots=bool(self.config.get('FLASHBOTS_RPC'))
        )
        
        logger.info("✅ All components initialized")

    def event_callback(self, event_type: str, data: Dict):
        """Callback when new event detected."""
        logger.info(f"🔔 Event: {event_type}")
        logger.info(f"   Data: {json.dumps(data, indent=2, default=str)}")
        
        if event_type == 'pool_created':
            self.on_pool_created(data)
        elif event_type == 'b20_created':
            self.on_b20_created(data)

    def on_pool_created(self, data: Dict):
        """New pool detected - analyze and potentially buy."""
        pool_address = data.get('pool_address')
        token_address = data.get('token_address')
        fee_tier = data.get('fee_tier')
        timestamp = data.get('timestamp')
        
        logger.info(f"🏊 New Pool: {pool_address}")
        logger.info(f"   Token: {token_address}")
        logger.info(f"   Fee: {fee_tier}")
        
        # Skip if already processed
        if pool_address in self.processed_pools:
            logger.debug(f"   ⏭ Already processed, skipping")
            return
        
        self.processed_pools.add(pool_address)
        
        # Add to pending queue for processing
        with self.lock:
            self.pending_pools.append({
                'pool_address': pool_address,
                'token_address': token_address,
                'fee_tier': fee_tier,
                'timestamp': timestamp
            })
        
        logger.info(f"✅ Added to processing queue ({len(self.pending_pools)} pending)")

    def on_b20_created(self, data: Dict):
        """New B20 token created."""
        token = data.get('token_address')
        name = data.get('name')
        symbol = data.get('symbol')
        
        logger.info(f"🆕 New B20: {name} ({symbol})")
        logger.info(f"   Address: {token}")
        
        # Log to database
        if self.db:
            self.db.log_event(
                'b20_created',
                'info',
                f"New B20 token: {name} ({symbol})",
                {
                    'token': token,
                    'name': name,
                    'symbol': symbol
                }
            )

    def process_pools(self):
        """Process pending pools and decide on buys."""
        while self.is_running:
            try:
                # Get next pool to process
                with self.lock:
                    if not self.pending_pools:
                        time.sleep(1)
                        continue
                    pool_data = self.pending_pools.pop(0)
                
                self._process_single_pool(pool_data)
                time.sleep(0.5)
            
            except Exception as e:
                logger.error(f"❌ Pool processing error: {e}")
                time.sleep(2)

    def _process_single_pool(self, pool_data: Dict):
        """Analyze single pool and execute if good."""
        pool_address = pool_data['pool_address']
        token_address = pool_data['token_address']
        fee_tier = pool_data['fee_tier']
        
        logger.info(f"🔍 Analyzing pool {pool_address[:8]}...")
        
        try:
            # Check pool age
            pool_age = self.event_monitor.get_pool_age_seconds(pool_address)
            min_age = 30  # Wait 30 seconds before buying
            
            if pool_age < min_age:
                logger.info(f"   ⏳ Pool too young ({pool_age:.1f}s < {min_age}s), wait...")
                # Re-queue for later
                with self.lock:
                    self.pending_pools.append(pool_data)
                return
            
            # Run safety checks
            logger.info(f"   🛡️ Running safety checks...")
            safety_scores = self.safety_analyzer.calculate_safety_score(
                token_address,
                pool_address,
                min_liquidity_eth=self.config.get('MIN_LIQUIDITY_ETH', 5.0)
            )
            
            overall_score = safety_scores.get('overall_score', 0)
            logger.info(f"   Safety Score: {overall_score}/100")
            
            # Log safety score
            if self.db:
                self.db.save_safety_score(
                    token_address,
                    safety_scores['overall_score'],
                    safety_scores.get('liquidity_score', 0),
                    safety_scores.get('holder_distribution_score', 0),
                    safety_scores.get('mint_authority_score', 0),
                    safety_scores.get('tax_score', 0),
                    safety_scores.get('rug_probability_score', 0),
                    safety_scores.get('honeypot_score', 0),
                    safety_scores
                )
            
            # Decide if we should buy
            should_buy, reason = self.safety_analyzer.should_buy(
                safety_scores,
                min_safety_score=75
            )
            
            if should_buy:
                logger.info(f"   ✅ PASSED SAFETY CHECK: {reason}")
                self._execute_buy(token_address, pool_address, fee_tier, safety_scores)
            else:
                logger.warning(f"   ❌ FAILED SAFETY CHECK: {reason}")
                # Blacklist if honeypot
                if safety_scores.get('honeypot_score', 0) < 50:
                    self.risk_mgr.blacklist_token(token_address)
                    logger.warning(f"   🚫 Blacklisted token (honeypot)")
        
        except Exception as e:
            logger.error(f"   Error analyzing pool: {e}")

    def _execute_buy(self, token: str, pool: str, fee: int, scores: Dict):
        """Execute buy if conditions met."""
        try:
            # Check if we can open position
            can_open, reason = self.risk_mgr.can_open_position(token)
            if not can_open:
                logger.warning(f"   Cannot open position: {reason}")
                return
            
            # Calculate position size
            position_size_eth = self.risk_mgr.calculate_position_size(
                wallet_balance_eth=1.0,  # TODO: get actual balance
                meme_score=scores.get('overall_score', 50) / 100,
                liquidity_eth=scores.get('liquidity_eth', 10)
            )
            
            logger.info(f"   💰 Position size: {position_size_eth:.4f} ETH")
            
            # Calculate slippage
            slippage_bps = self.execution_engine.calculate_dynamic_slippage(
                amount_in_wei=self.w3.to_wei(position_size_eth, 'ether'),
                pool_liquidity_eth=scores.get('liquidity_eth', 10),
                volatility_score=0.5
            )
            
            logger.info(f"   📊 Dynamic slippage: {slippage_bps/100:.2f}%")
            
            # TODO: Execute actual swap via execution_engine
            # For now, just log
            logger.info(f"   ✅ BUY SIGNAL READY (execution not implemented in monitor)")
            
            if self.db:
                self.db.log_event(
                    'buy_signal',
                    'info',
                    f'Buy signal for {token}',
                    {
                        'token': token,
                        'position_size_eth': position_size_eth,
                        'slippage_bps': slippage_bps,
                        'safety_score': scores.get('overall_score', 0)
                    }
                )
        
        except Exception as e:
            logger.error(f"   Error executing buy: {e}")

    def monitor_loop(self):
        """Main monitoring loop."""
        logger.info("🔄 Starting event monitoring...")
        
        # Start event listening in background threads
        monitor_thread = threading.Thread(
            target=self.event_monitor.listen_pool_created,
            args=(self.event_callback,),
            daemon=True
        )
        monitor_thread.start()
        
        b20_thread = threading.Thread(
            target=self.event_monitor.listen_b20_created,
            args=(self.event_callback,),
            daemon=True
        )
        b20_thread.start()
        
        # Start pool processing thread
        process_thread = threading.Thread(
            target=self.process_pools,
            daemon=True
        )
        process_thread.start()
        
        logger.info("✅ Event monitoring started")
        logger.info("🟢 Monitor running - waiting for pools...")
        
        # Keep main loop alive
        try:
            while self.is_running:
                # Log status periodically
                if len(self.pending_pools) > 0:
                    logger.info(f"📋 Pending pools: {len(self.pending_pools)}")
                
                time.sleep(30)
        
        except KeyboardInterrupt:
            logger.info("⏹ Stopping monitor...")
            self.is_running = False

    def run(self):
        """Main entry point."""
        try:
            self.initialize()
            self.monitor_loop()
        except Exception as e:
            logger.error(f"❌ Fatal error: {e}")
            sys.exit(1)


def main():
    """Load config and start monitor."""
    load_dotenv()
    
    config = {
        'RPC_URL': os.getenv('RPC_URL', 'https://mainnet.base.org'),
        'PRIVATE_KEY': os.getenv('PRIVATE_KEY', ''),
        'FLASHBOTS_RPC': os.getenv('FLASHBOTS_RPC', ''),
        'MAX_TRADE_ETH': float(os.getenv('MAX_TRADE_ETH', '0.1')),
        'MAX_DAILY_LOSS_ETH': float(os.getenv('MAX_DAILY_LOSS_ETH', '0.5')),
        'MIN_LIQUIDITY_ETH': float(os.getenv('MIN_LIQUIDITY_ETH', '5.0')),
        'TG_BOT_TOKEN': os.getenv('TG_BOT_TOKEN', ''),
        'TG_USER_ID': os.getenv('TG_USER_ID', ''),
    }
    
    monitor = B20Monitor(config)
    monitor.run()


if __name__ == '__main__':
    main()
