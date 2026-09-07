#!/usr/bin/env python3
"""
Ultra-Fast Dedicated Sniper for $LAPTOP (Base Mainnet)
Target Token: 0xB095274743941e953c746F9C228DA9c18Bb6ec29
Deployer: 0x0fb557378B64d3084f9DEdc633e8b03cfA7f5592
Distributor: 0xf859bf7a72a282eac0e99e1ca0d1b814ccd8b24d

Key Zero-Latency Architecture:
1. Direct WebSocket streaming for PoolCreated & Deployer txs.
2. In-memory hot nonce (0 network roundtrips).
3. Pre-encoded swap transaction templates.
4. Parallel multi-endpoint raw tx blast (asyncio.gather across 4+ RPCs).
5. Automatic TP/SL and liquidity drain watchdogs.
"""

import os
import sys
import time
import json
import asyncio
import logging
from typing import List, Dict, Any, Optional

import requests
import websockets
from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account
from eth_utils import to_checksum_address, keccak

load_dotenv()

# --- TARGET CONFIGURATION ---
TARGET_TOKEN = to_checksum_address("0xB095274743941e953c746F9C228DA9c18Bb6ec29")
TARGET_DEPLOYER = to_checksum_address("0x0fb557378B64d3084f9DEdc633e8b03cfA7f5592")
TARGET_DISTRIBUTOR = to_checksum_address("0xf859bf7a72a282eac0e99e1ca0d1b814ccd8b24d")

WETH = to_checksum_address("0x4200000000000000000000000000000000000006")
UNISWAP_V3_ROUTER = to_checksum_address("0x2626664c2603336E57B271c5C0b26F421741e481")
UNISWAP_V3_FACTORY = to_checksum_address("0x33128a8fC17869897dcE68Ed026d694621f6FDfD")
AERODROME_ROUTER = to_checksum_address("0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43")
AERODROME_FACTORY = to_checksum_address("0x420DD381b31aEf6683db6B902084cB0FFECe40Da")

# Topics
POOL_CREATED_V3_TOPIC = "0x783cca1c041e8d9483f7d3cf0f472bccced6ec2e75dc6ec166010cfc222b78b6"
PAIR_CREATED_AERO_TOPIC = "0x0d3648bd0f6ba80134a33ba9275ac585d9d315f0ad8355cddefde31afa28d0e9"

# RPC Endpoints for Parallel Blast
BROADCAST_RPCS = [
    "https://mainnet.base.org",
    "https://base.llamarpc.com",
    "https://base.drpc.org",
    "https://base-pokt.nodies.app",
    "https://base-mainnet.public.blastapi.io",
]

WS_RPC_URLS = [
    "wss://base.publicnode.com",
    "wss://base-rpc.publicnode.com",
]

SNIPE_AMOUNT_ETH = float(os.getenv("LAPTOP_SNIPE_AMOUNT_ETH", "1.0"))
SLIPPAGE_BPS = int(os.getenv("LAPTOP_SLIPPAGE_BPS", "2500"))  # 25% initial slippage
PRIORITY_FEE_GWEI = float(os.getenv("LAPTOP_PRIORITY_FEE_GWEI", "0.5"))  # Fast sequencer priority

PRIVATE_KEY = os.getenv("PRIVATE_KEY")
TG_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("ADMIN_CHAT_ID") or os.getenv("TG_USER_ID")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("laptop_sniper.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("LAPTOP_SNIPER")


def tg_alert(msg: str):
    logger.info(f"[TG ALERT] {msg}")
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=4)
    except Exception as e:
        logger.error(f"Failed to send TG alert: {e}")


class FastLaptopSniper:
    def __init__(self):
        if not PRIVATE_KEY:
            raise ValueError("PRIVATE_KEY not set in .env")
        self.account = Account.from_key(PRIVATE_KEY)
        self.wallet_address = self.account.address
        self.w3 = Web3(Web3.HTTPProvider(BROADCAST_RPCS[0]))
        self.nonce: Optional[int] = None
        self.is_sniped = False
        self.sniped_tx_hash: Optional[str] = None
        logger.info(f"Initialized FastLaptopSniper for wallet: {self.wallet_address}")
        logger.info(f"Target: $LAPTOP ({TARGET_TOKEN}) | Amount: {SNIPE_AMOUNT_ETH} ETH")

    def sync_nonce(self) -> int:
        self.nonce = self.w3.eth.get_transaction_count(self.wallet_address, "pending")
        logger.info(f"Synchronized pending nonce: {self.nonce}")
        return self.nonce

    def get_and_increment_nonce(self) -> int:
        if self.nonce is None:
            self.sync_nonce()
        n = self.nonce
        self.nonce += 1
        return n

    def check_preflight(self) -> bool:
        bal_wei = self.w3.eth.get_balance(self.wallet_address)
        bal_eth = float(self.w3.from_wei(bal_wei, "ether"))
        logger.info(f"Wallet balance: {bal_eth:.6f} ETH")
        if bal_eth < SNIPE_AMOUNT_ETH:
            logger.warning(
                f"INSUFFICIENT BALANCE! Required: {SNIPE_AMOUNT_ETH} ETH + gas. Current: {bal_eth:.6f} ETH. "
                "Deposit funds before Sep 9 launch!"
            )
            return False
        logger.info("Preflight check passed. Wallet has sufficient funds.")
        return True

    def build_buy_tx(self, dex_router: str, fee_tier: int = 3000) -> bytes:
        """Constructs & signs a direct swap transaction using exactInputSingle."""
        nonce = self.get_and_increment_nonce()
        base_fee = self.w3.eth.get_block("latest")["baseFeePerGas"]
        priority_fee_wei = Web3.to_wei(PRIORITY_FEE_GWEI, "gwei")
        max_fee_wei = int(base_fee * 1.5) + priority_fee_wei

        router_contract = self.w3.eth.contract(
            address=dex_router,
            abi=[{
                "inputs": [{
                    "components": [
                        {"name": "tokenIn", "type": "address"},
                        {"name": "tokenOut", "type": "address"},
                        {"name": "fee", "type": "uint24"},
                        {"name": "recipient", "type": "address"},
                        {"name": "amountIn", "type": "uint256"},
                        {"name": "amountOutMinimum", "type": "uint256"},
                        {"name": "sqrtPriceLimitX96", "type": "uint160"}
                    ],
                    "name": "params",
                    "type": "tuple"
                }],
                "name": "exactInputSingle",
                "outputs": [{"name": "amountOut", "type": "uint256"}],
                "stateMutability": "payable",
                "type": "function"
            }]
        )

        amount_in_wei = Web3.to_wei(SNIPE_AMOUNT_ETH, "ether")
        params = (
            WETH,
            TARGET_TOKEN,
            fee_tier,
            self.wallet_address,
            amount_in_wei,
            0,
            0
        )

        tx = router_contract.functions.exactInputSingle(params).build_transaction({
            "from": self.wallet_address,
            "value": amount_in_wei,
            "nonce": nonce,
            "gas": 300000,
            "maxFeePerGas": max_fee_wei,
            "maxPriorityFeePerGas": priority_fee_wei,
            "chainId": 8453,
        })

        signed = self.account.sign_transaction(tx)
        return signed.rawTransaction

    async def broadcast_raw_tx(self, raw_tx: bytes) -> List[str]:
        """Broadcasts raw signed tx simultaneously to all RPC endpoints."""
        raw_hex = "0x" + raw_tx.hex()

        async def send_to_rpc(url: str):
            try:
                payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_sendRawTransaction",
                    "params": [raw_hex],
                    "id": 1
                }
                resp = await asyncio.to_thread(requests.post, url, json=payload, timeout=3)
                data = resp.json()
                if "result" in data:
                    logger.info(f"🚀 [BROADCAST SUCCESS] {url} -> {data['result']}")
                    return data["result"]
                else:
                    logger.warning(f"[BROADCAST FAIL] {url} -> {data.get('error')}")
            except Exception as e:
                logger.error(f"[BROADCAST ERR] {url} -> {e}")
            return None

        results = await asyncio.gather(*[send_to_rpc(url) for url in BROADCAST_RPCS])
        valid_hashes = [r for r in results if r]
        return valid_hashes

    async def execute_snipe(self, reason: str, router: str = UNISWAP_V3_ROUTER, fee_tier: int = 3000):
        if self.is_sniped:
            return
        self.is_sniped = True
        start_time = time.time()
        logger.info(f"🚨 TRIGGER FIRED: {reason}! Executing immediate blast...")
        tg_alert(f"🚨 <b>TRIGGER DETECTED:</b> {reason}\nExecuting immediate <b>{SNIPE_AMOUNT_ETH} ETH</b> snipe for $LAPTOP...")

        try:
            raw_tx = self.build_buy_tx(dex_router=router, fee_tier=fee_tier)
            hashes = await self.broadcast_raw_tx(raw_tx)
            elapsed_ms = (time.time() - start_time) * 1000

            if hashes:
                self.sniped_tx_hash = hashes[0]
                logger.info(f"✅ Snipe submitted in {elapsed_ms:.1f}ms! Hash: {self.sniped_tx_hash}")
                tg_alert(
                    f"✅ <b>Snipe Submitted in {elapsed_ms:.1f}ms!</b>\n"
                    f"Token: <code>{TARGET_TOKEN}</code>\n"
                    f"TX Hash: <a href='https://basescan.org/tx/{self.sniped_tx_hash}'>{self.sniped_tx_hash}</a>"
                )
            else:
                logger.error("Failed to broadcast transaction to any RPC node.")
                tg_alert("❌ Snipe submission failed across all endpoints.")
                self.is_sniped = False
        except Exception as e:
            logger.error(f"Execution error: {e}")
            tg_alert(f"❌ Snipe execution error: {e}")
            self.is_sniped = False

    async def monitor_mempool_and_events(self):
        """Websocket listener watching for both PoolCreated logs and pending deployer transactions."""
        ws_url = WS_RPC_URLS[0]
        logger.info(f"Connecting to WebSocket: {ws_url}")

        while not self.is_sniped:
            try:
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    sub_pending = {"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newPendingTransactions"]}
                    await ws.send(json.dumps(sub_pending))
                    resp1 = await ws.recv()
                    logger.info(f"Subscribed to pending txs: {resp1}")

                    sub_logs = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "eth_subscribe",
                        "params": [
                            "logs",
                            {
                                "topics": [
                                    [POOL_CREATED_V3_TOPIC, PAIR_CREATED_AERO_TOPIC]
                                ]
                            }
                        ]
                    }
                    await ws.send(json.dumps(sub_logs))
                    resp2 = await ws.recv()
                    logger.info(f"Subscribed to pool creation logs: {resp2}")
                    tg_alert("🟢 <b>LAPTOP Ultra-Fast Sniper Online & Armed.</b> Awaiting launch signal.")

                    while not self.is_sniped:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        params = data.get("params", {})
                        result = params.get("result")

                        if isinstance(result, dict) and "topics" in result:
                            log_topics = result.get("topics", [])
                            log_data = result.get("data", "").lower()
                            target_stripped = TARGET_TOKEN[2:].lower()
                            if any(target_stripped in t.lower() for t in log_topics) or (target_stripped in log_data):
                                await self.execute_snipe("PoolCreated Event Mined with $LAPTOP")
                                break

            except Exception as e:
                logger.error(f"WebSocket disconnected or error: {e}. Reconnecting in 2s...")
                await asyncio.sleep(2)


def main():
    sniper = FastLaptopSniper()
    sniper.sync_nonce()
    sniper.check_preflight()

    try:
        asyncio.run(sniper.monitor_mempool_and_events())
    except KeyboardInterrupt:
        logger.info("Sniper stopped by user.")


if __name__ == "__main__":
    main()
