# 🏛️ Lighter & Hyperliquid Institutional Trading Bot

> **High-Performance Multi-DEX Algorithmic Trading, News Catalyst Sniping, 0-Fee Market Making, and Risk-Managed Execution.**

![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![zkLighter](https://img.shields.io/badge/DEX-zkLighter%20Mainnet-purple.svg)
![Hyperliquid](https://img.shields.io/badge/DEX-Hyperliquid%20L1-green.svg)
![Tests](https://img.shields.io/badge/Tests-325%2F325%20Passing-brightgreen.svg)
![Status](https://img.shields.io/badge/Status-24%2F7%20Live%20Production-success.svg)

---

## 📑 Overview

This repository houses an institutional-grade, multi-venue algorithmic trading architecture designed for **zkLighter Mainnet CLOB** and **Hyperliquid L1 Perps & Spot**. It combines sub-15ms news ingestion, 0-fee market making quoting, cross-exchange price-lag arbitrage, on-chain whale copy-trading, and multi-stage risk management ladders with 24/7 self-healing VPS supervision.

---

## 💼 Live Production Portfolio

| Exchange Venue | Account Identifier | Allocation & Role | Active Status |
| :--- | :--- | :--- | :---: |
| **zkLighter Mainnet** | Subaccount **`#737649`** | **`$730.09 USDC`** • Breaking News Sniping & 0-Fee Points Quoting | 🟢 **ACTIVE** |
| **Hyperliquid L1** | Master: `0x5cE9...cFe9`<br>Agent: `0xC0c5...Bbdc` | **`$10.7744 USDC`** • 25 bps Cross-DEX Arb & Top 20 Whale Copy-Trader | 🟢 **ACTIVE** |
| **Combined Portfolio** | **Unified Multi-DEX** | **`$740.86 USD`** • Dynamic Kelly Compounding + 20% Profit Lock Vault | 🟢 **ARMED** |

---

## 🧩 Subaccount Sharding Architecture

To eliminate strategy interference and isolate margin risks, capital is partitioned into 3 specialized subaccount shards:

1. **Shard 1 (`#737649`) — Catalyst Sniper & Copilot**:
   - Sub-15ms execution on breaking news events.
   - Precision lot/tick integer math with microsecond fast signing.
   - Dedicated margin partition for high-conviction taker snipes.
2. **Shard 2 (`#281474976497685`) — 0-Fee Market Maker**:
   - Avellaneda-Stoikov quoting on top perpetuals (ETH, BTC, SOL, TRUMP, HYPE).
   - Captures bid-ask spread and farms zkLighter ecosystem points with 0% maker fees.
   - Sub-2ms Anti-Toxic Cancel Guard instantly pulls quotes before toxic orderflow hits.
3. **Shard 3 (`#281474976497686`) — Arbitrage & Treasury**:
   - Captures cross-venue funding rate yield and statistical cointegration spreads.
   - Automated profit-sweeper locks 20% of net realized gains in cold reserve.

---

## ⚡ The 7 Core Alpha Engines

```
 ┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                   🧠 7 AUTONOMOUS ALPHA ENGINES                                        │
 ├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │                                                                                                        │
 │  1️⃣  ⚡ TreeNews & Fast-Feed Catalyst Sniper (`news_pipeline.py`, `lighter_news_sniper.py`)             │
 │      • Sub-15ms WebSocket ingestion from TreeNews, Binance, Coinbase, Upbit, Bithumb, SEC EDGAR.     │
 │      • Tier-1 single-source execution with a 15-minute story fingerprint lockout (no duplicate re-buy).│
 │                                                                                                        │
 │  2️⃣  🌾 0-Fee Avellaneda-Stoikov Quoting & Points Farmer (`lighter_mm_bot.py`)                        │
 │      • Captures bid-ask spreads and farms zkLighter points with 0% maker fees.                         │
 │      • Sub-2ms Anti-Toxic Lead-Cancel Guard pulls quotes before adverse price moves arrive.           │
 │                                                                                                        │
 │  3️⃣  ⚡ Hyperliquid Price-Lag Cross-DEX Arbitrage (`cross_dex_arbitrage.py`)                          │
 │      • Detects when Hyperliquid mark price leads zkLighter orderbook by ≥ 25 bps (0.25%).              │
 │                                                                                                        │
 │  4️⃣  🐋 On-Chain Whale Copy-Trader (`whale_copy_trader.py`)                                           │
 │      • Monitors top 20 profitable Hyperliquid whales (≥ $250k positions) and mirrors trades.          │
 │                                                                                                        │
 │  5️⃣  ⚡ Liquidation Cascade & Wick Hunter (`liquidation_hunter.py`)                                    │
 │      • Snipes ≥ $2,000,000 forced liquidation cascades for +1.5%..+3.0% mean-reversion counter wicks.  │
 │                                                                                                        │
 │  6️⃣  ⚖️ Statistical Pairs & Cointegration (`stat_arb_pairs.py`)                                       │
 │      • Delta-neutral Long/Short on SOL/ETH, ETH/BTC, AVAX/SOL when spread diverts |Z| ≥ 2.50σ.         │
 │                                                                                                        │
 │  7️⃣  🧠 Market Regime & Fear/Greed Posture Switch (`market_regime_adapter.py`)                        │
 │      • Ingests Fear & Greed Index, Funding APR, and ATR volatility to dynamically adapt TP/SL spreads.│
 │                                                                                                        │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🛡️ Risk Management & Exit Ladder

* **VWAP Depth & Slippage Protection**: Evaluates orderbook liquidity; strictly clamps orders to avoid exceeding a 50 bps max slippage tolerance.
* **Multi-Stage Take-Profit Ladder**:
  * **TP1 (+2.5%)**: Closes **50%** position $\rightarrow$ automatically shifts Stop-Loss to **Breakeven (+0.1%)**.
  * **TP2 (+4.0%)**: Closes **25%** position.
  * **Runner (25%)**: Runs with a **1.0% dynamic trailing stop** to ride trending momentum.
* **Hard On-Chain Stop-Loss (-1.5%)**: Guaranteed on-chain GTT trigger orders protect every trade against flash dumps.
* **Hyperliquid Sub-50ms Margin Balancing**: Automated `usdClassTransfer` moves idle Spot USDC into Perps margin seamlessly.

---

## 🖥️ 24/7 VPS Infrastructure & Self-Healing

The bot operates continuously on Windows Server VPS (`18.153.70.154`) with a 4-layer auto-revive guard:

```
                  ┌─────────────────────────────────────────┐
                  │    Windows Task Scheduler (ONSTART)     │
                  └────────────────────┬────────────────────┘
                                       │ Launches on Boot
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │     Python Watchdog Supervisor (2s)     │
                  │        (watchdog_supervisor.py)         │
                  └────────────┬────────────────────────────┘
                               │ Supervises & Rotates Logs (25MB)
                               ▼
        ┌─────────────────────────────────────────────────────────┐
        │   Live Trading Engine (`lighter_news_sniper.py`)        │
        │   • zkLighter Mainnet Execution                         │
        │   • Hyperliquid Execution & Margin Balancing            │
        │   • 610+ Feed Catalyst Pipeline                         │
        │   • Telegram Fast Zero-Lag Bot Interface                │
        └─────────────────────────────────────────────────────────┘
                               ▲
                               │ 60s Heartbeat Check
                  ┌────────────┴────────────────────────────┐
                  │          LighterRespawnGuard            │
                  │   (Auto-Revives If Process Dies)        │
                  └─────────────────────────────────────────┘
```

---

## 📲 Telegram Copilot Controls (`@lightertr_bot`)

Full remote control from mobile Telegram:

| Command | Action / Description |
| :--- | :--- |
| **`/status`** | Real-time zkLighter collateral, active coverage, and engine health |
| **`/hl`** | Live Hyperliquid equity (`$10.77 USDC`), active positions, and 1-tap spot/perp transfer |
| **`/positions`** | Open positions with 1-tap **Breakeven**, **Close 50%**, **+2% TP**, and **Chart** buttons |
| **`/funding`** | Real-time 3-way funding rate heatmap (zkLighter vs Hyperliquid vs Binance) |
| **`/copy`** | Active top 20 on-chain whale tracker telemetry |
| **`/regime`** | Fear & Greed Index score and active strategy posture |
| **`/report`** | Daily 24h net PnL, win rate %, and total farmed volume |
| **`/tweet`** | Broadcast custom messages directly to Twitter/X |
| **Natural Language** | Conversational commands (e.g. *"how much volume today?"*, *"breakeven TRUMP"*, *"snipe $50 SOL"*) |

---

## 🧪 Testing & Verification

Run the full 325-test unit and integration test suite:

```bash
pytest tests/ -v
```

```text
====================== 325 passed in 18.25s (100% Pass Rate) ======================
```

---

## 💾 Disaster Recovery Runbook

A permanent release backup tag is maintained on GitHub:
* **Release Tag**: **`v2.0-stable-production-backup`**
* **Runbook Guide**: [`BACKUP_STRATEGY_RUNBOOK.md`](BACKUP_STRATEGY_RUNBOOK.md) for 1-click strategy restoration anytime.

---

## 🔒 Security & Privacy

* API Keys, Private Keys, and Telegram tokens are strictly handled via encrypted environment variables and local `.env`.
* Zero private keys or credentials are ever exposed in public repos.
