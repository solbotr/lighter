#!/usr/bin/env python3
"""
Event Monitoring Module for B20 Bot
===================================
Advanced event detection:
- B20Factory B20Created event monitoring (early detection)
- Uniswap V3 PoolCreated monitoring (existing + enhanced)
- Mempool watching via WebSocket
- Volume spike detection
- Pool age tracking
"""

import asyncio
import json
import time
from typing import Callable, Optional, Dict, List, Any
from datetime import datetime, timezone
from web3 import Web3
from web3.contract import AsyncContract
from eth_utils import to_checksum_address, keccak
import logging


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EventMonitor:
    """Monitor B20Factory and Uniswap V3 events with multiple parallel streams."""

    def __init__(self, w3: Web3, b20_factory: str, v3_factory: str, weth: str):
        self.w3 = w3
        self.b20_factory = to_checksum_address(b20_factory)
        self.v3_factory = to_checksum_address(v3_factory)
        self.weth = to_checksum_address(weth)
        
        # Track seen pools/tokens to avoid duplicates
        self.seen_pools = set()
        self.seen_tokens = set()
        self.pool_creation_times = {}  # pool_address -> timestamp
        self.pool_liquidity = {}  # pool_address -> current_liquidity (amount uint128)
        
        # ABIs
        self.b20_factory_abi = [
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "internalType": "address", "name": "token", "type": "address"},
                    {"indexed": False, "internalType": "uint8", "name": "variant", "type": "uint8"},
                    {"indexed": False, "internalType": "string", "name": "name", "type": "string"},
                    {"indexed": False, "internalType": "string", "name": "symbol", "type": "string"},
                ],
                "name": "B20Created",
                "type": "event"
            }
        ]
        
        self.v3_factory_abi = [
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "internalType": "address", "name": "token0", "type": "address"},
                    {"indexed": True, "internalType": "address", "name": "token1", "type": "address"},
                    {"indexed": True, "internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"indexed": False, "internalType": "int24", "name": "tickSpacing", "type": "int24"},
                    {"indexed": False, "internalType": "address", "name": "pool", "type": "address"}
                ],
                "name": "PoolCreated",
                "type": "event"
            }
        ]

    # =========== B20FACTORY MONITORING ===========
    def listen_b20_created(self, callback: Callable) -> None:
        """
        Listen for B20Created events from B20Factory.
        Calls callback(token_address, name, symbol) when new token created.
        """
        try:
            b20_factory = self.w3.eth.contract(
                address=self.b20_factory,
                abi=self.b20_factory_abi
            )
            
            event_filter = b20_factory.events.B20Created.create_filter(from_block='latest')
            
            logger.info("Listening for B20Created events...")
            
            while True:
                try:
                    for event in event_filter.get_new_entries():
                        token = event['args']['token']
                        name = event['args']['name']
                        symbol = event['args']['symbol']
                        
                        if token not in self.seen_tokens:
                            self.seen_tokens.add(token)
                            logger.info(f"New B20: {name} ({symbol}) at {token}")
                            callback('b20_created', {
                                'token_address': token,
                                'name': name,
                                'symbol': symbol,
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            })
                    
                    # Re-create filter periodically
                    # event_filter = b20_factory.events.B20Created.create_filter(from_block='latest')
                    
                except Exception as e:
                    logger.error(f"B20Created filter error: {e}")
                    time.sleep(2)
        
        except Exception as e:
            logger.error(f"Failed to listen for B20Created: {e}")

    # =========== UNISWAP V3 POOL MONITORING ===========
    def listen_pool_created(
        self, callback: Callable, min_pool_age_seconds: int = 30
    ) -> None:
        """
        Listen for PoolCreated events from Uniswap V3.
        Filters for WETH pairs only.
        Includes pool age tracking.
        """
        try:
            v3_factory = self.w3.eth.contract(
                address=self.v3_factory,
                abi=self.v3_factory_abi
            )
            
            event_filter = v3_factory.events.PoolCreated.create_filter(from_block='latest')
            
            logger.info("Listening for PoolCreated events...")
            
            while True:
                try:
                    for event in event_filter.get_new_entries():
                        token0 = event['args']['token0']
                        token1 = event['args']['token1']
                        fee = event['args']['fee']
                        pool = event['args']['pool']
                        
                        # Only process WETH pairs
                        if token0.lower() == self.weth.lower():
                            token = token1
                        elif token1.lower() == self.weth.lower():
                            token = token0
                        else:
                            continue
                        
                        if pool not in self.seen_pools:
                            self.seen_pools.add(pool)
                            now = datetime.now(timezone.utc)
                            self.pool_creation_times[pool] = now
                            
                            logger.info(f"New pool: {pool} for token {token} (fee {fee})")
                            callback('pool_created', {
                                'pool_address': pool,
                                'token_address': token,
                                'fee_tier': fee,
                                'timestamp': now.isoformat()
                            })
                
                except Exception as e:
                    logger.error(f"PoolCreated filter error: {e}")
                    time.sleep(2)
        
        except Exception as e:
            logger.error(f"Failed to listen for PoolCreated: {e}")

    # =========== POOL AGE FILTERING ===========
    def is_pool_old_enough(self, pool_address: str, min_age_seconds: int = 30) -> bool:
        """
        Check if pool is old enough to trade on.
        Helps avoid immediate rugs and scams.
        """
        if pool_address not in self.pool_creation_times:
            return False
        
        age = (datetime.now(timezone.utc) - self.pool_creation_times[pool_address]).total_seconds()
        return age >= min_age_seconds

    def get_pool_age_seconds(self, pool_address: str) -> float:
        """Get pool age in seconds."""
        if pool_address not in self.pool_creation_times:
            return 0.0
        return (datetime.now(timezone.utc) - self.pool_creation_times[pool_address]).total_seconds()

    # =========== MEMPOOL MONITORING (ASYNC) ===========
    async def listen_mempool_pending_txs(self, callback: Callable, poll_interval: float = 0.5) -> None:
        """
        Monitor pending transactions in mempool via WebSocket.
        Looks for PoolCreated / swap txs.
        """
        try:
            # This requires a WebSocket RPC
            logger.info("Starting mempool monitoring (requires WebSocket RPC)...")
            
            # Register for new pending transactions
            # Note: This is simplified; real implementation would filter for relevant txs
            
            logger.warning("Mempool monitoring not fully implemented - requires WebSocket setup")
            
        except Exception as e:
            logger.error(f"Mempool monitoring error: {e}")

    # =========== VOLUME SPIKE DETECTION ===========
    def detect_volume_spike(
        self, pool_address: str, current_volume: float, baseline_volume: float,
        spike_threshold: float = 5.0  # 5x volume = spike
    ) -> tuple[bool, float]:
        """
        Detect volume spikes on new pools.
        Returns: (is_spike, volume_ratio)
        """
        if baseline_volume == 0:
            return (False, 0.0)
        
        ratio = current_volume / baseline_volume
        is_spike = ratio >= spike_threshold
        
        return (is_spike, ratio)

    # =========== MEME DETECTION ===========
    def is_meme_like(self, name: str, symbol: str) -> Tuple[bool, List[str], float]:
        """
        Detect if token name/symbol looks like a meme.
        Returns: (is_meme, matched_patterns, confidence_score)
        """
        meme_patterns = [
            # Animals
            'PEPE', 'DOGE', 'SHIB', 'CAT', 'DOG', 'APE', 'FROG', 'PANDA', 'BEAR', 'BULL',
            # Meme references
            'MEME', 'MOON', 'LAMBORGHINI', 'ROCKET', 'DIAMOND', 'HANDS', 'HODL', 'TO_THE_MOON',
            # Recent meme coins
            'FLOKI', 'KISHU', 'SQUID', 'SAFE', 'ELON', 'BABY', 'ELONGATE', 'AKITA',
            # Patterns
            'INU', 'COIN', 'TOKEN', 'OFFICIAL',
        ]
        
        combined = f"{name} {symbol}".upper()
        matched = []
        
        for pattern in meme_patterns:
            if pattern in combined:
                matched.append(pattern)
        
        # Scoring
        is_meme = len(matched) > 0
        confidence = len(matched) / len(meme_patterns) * 100 if len(meme_patterns) > 0 else 0
        
        return (is_meme, matched, confidence)

    # =========== MALICIOUS PATTERN DETECTION ===========
    def check_malicious_patterns(self, name: str, symbol: str) -> List[str]:
        """
        Check for known malicious patterns in token name/symbol.
        """
        warnings = []
        
        # Known copycat tokens
        famous_brands = ['ETHEREUM', 'BITCOIN', 'BINANCE', 'OPENSEA', 'METAMASK', 'UNISWAP']
        for brand in famous_brands:
            if brand in name.upper():
                warnings.append(f"Impersonates {brand}")
        
        # Suspicious patterns
        if len(name) > 50:
            warnings.append("Unusually long name")
        
        if symbol and len(symbol) > 10:
            warnings.append("Unusually long symbol")
        
        if '0' in symbol and 'O' in symbol:
            warnings.append("Ambiguous 0/O in symbol")
        
        if name.lower().count('moon') > 2 or name.lower().count('moon') > 2:
            warnings.append("Excessive 'moon' references")
        
        return warnings

    # =========== STEALTH LAUNCH DETECTION ===========
    def is_stealth_launch(self, token_age_seconds: float, pool_age_seconds: float) -> bool:
        """
        Detect stealth launches (createB20 + immediate pool in same block).
        Returns True if both happen within <2 seconds (same block).
        """
        return abs(token_age_seconds - pool_age_seconds) < 2.0

    # =========== LIQUIDITY MONITORING ===========
    def listen_liquidity_events(self, callback: Callable) -> None:
        """
        Listen for Mint and Burn events from Uniswap V3 pools.
        """
        try:
            mint_topic = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
            burn_topic = "0xcc1091283307613764841b5273397f26d7f8d6600c921319228807d925d48227"
            
            logger.info("Listening for Uniswap V3 Mint and Burn events...")
            
            last_block = self.w3.eth.block_number
            while True:
                try:
                    current_block = self.w3.eth.block_number
                    if current_block > last_block:
                        logs = self.w3.eth.get_logs({
                            "fromBlock": last_block + 1,
                            "toBlock": current_block,
                            "topics": [[mint_topic, burn_topic]]
                        })
                        for log in logs:
                            pool = log['address']
                            topic0 = log['topics'][0].hex()
                            data = log['data']
                            
                            try:
                                amount = int.from_bytes(data[0:32], 'big')
                                amount0 = int.from_bytes(data[32:64], 'big')
                                amount1 = int.from_bytes(data[64:96], 'big')
                            except Exception:
                                amount, amount0, amount1 = 0, 0, 0
                                
                            change_type = 'add' if topic0 == mint_topic else 'remove'
                            
                            # Update tracked liquidity
                            current_liq = self.pool_liquidity.get(pool, 0)
                            if change_type == 'add':
                                self.pool_liquidity[pool] = current_liq + amount
                            else:
                                self.pool_liquidity[pool] = max(0, current_liq - amount)
                                
                            now = datetime.now(timezone.utc)
                            callback('liquidity_change', {
                                'pool_address': pool,
                                'change_type': change_type,
                                'amount': amount,
                                'amount0': amount0,
                                'amount1': amount1,
                                'current_liquidity': self.pool_liquidity[pool],
                                'timestamp': now.isoformat()
                            })
                            
                        last_block = current_block
                    time.sleep(2)
                except Exception as e:
                    logger.error(f"Liquidity monitor polling error: {e}")
                    time.sleep(2)
        except Exception as e:
            logger.error(f"Failed to start liquidity monitor: {e}")

    # =========== EVENT AGGREGATION ===========
    def start_monitoring(self, callback: Callable) -> None:
        """
        Start all monitoring streams in parallel.
        Callback signature: callback(event_type: str, data: Dict)
        """
        import threading
        
        threads = [
            threading.Thread(target=self.listen_b20_created, args=(callback,), daemon=True),
            threading.Thread(target=self.listen_pool_created, args=(callback,), daemon=True),
            threading.Thread(target=self.listen_liquidity_events, args=(callback,), daemon=True),
        ]
        
        for t in threads:
            t.start()
        
        logger.info("All event monitors started")
        
        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Monitoring stopped")
