# 🏛️ Lighter & Hyperliquid Institutional Trading Bot

> **Multi-DEX algorithmic trading: news catalyst sniping (live), Avellaneda-Stoikov market making (opt-in), and risk-managed execution.**

![Python](https://img.shields.io/badge/Python-3.12-blue.svg)
![zkLighter](https://img.shields.io/badge/DEX-zkLighter%20Mainnet-purple.svg)
![Hyperliquid](https://img.shields.io/badge/DEX-Hyperliquid%20L1-green.svg)
![Tests](https://img.shields.io/badge/Tests-394%20Passing-brightgreen.svg)
![Status](https://img.shields.io/badge/Status-24%2F7%20Live%20Production-success.svg)

---

## 📑 Overview

This repository houses an institutional-grade, multi-venue algorithmic trading architecture designed for **zkLighter Mainnet CLOB** and **Hyperliquid L1 Perps & Spot**. It combines fast news ingestion (TreeNews WebSocket live; polled RSS shadow-only), an opt-in Avellaneda-Stoikov market maker (0 bps on a Standard-tier subaccount), and multi-stage risk management with 24/7 self-healing VPS supervision.

---

## 💼 Live Production Portfolio

| Exchange Venue | Account Identifier | Allocation & Role | Active Status |
| :--- | :--- | :--- | :---: |
| **zkLighter Mainnet** | Subaccount **`#737649`** | **`$730.09 USDC`** • Breaking News Sniping & 0-Fee Points Quoting | 🟢 **ACTIVE** |
| **Hyperliquid L1** | Master: `0x5cE9...cFe9`<br>Agent: `0xC0c5...Bbdc` | **`$10.7744 USDC`** • 25 bps Cross-DEX Arb & Top 20 Whale Copy-Trader | 🟢 **ACTIVE** |
| **Combined Portfolio** | **Unified Multi-DEX** | **`$740.86 USD`** • Dynamic Kelly Compounding + 20% Profit Lock Vault | 🟢 **ARMED** |

---

## 🧩 Subaccount Sharding Architecture

Target layout (only Shard 1 runs by default; Shard 2 starts when `MM_ENABLED=1`, Shard 3 is not wired to any process):

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

```bash
python3 -m pytest tests/ -q
```

```text
394 passed in ~9s
```

## 🛠️ What actually runs (read this before trusting the marketing above)

- **Production entrypoint** is `watchdog_supervisor.py` (run_247.bat / Dockerfile). It always runs `lighter_news_sniper.py`; it runs `lighter_mm_bot.py` only when `MM_ENABLED=1` (see `MM_DEPLOY.md`).
- **Fees**: Lighter Standard tier is 0/0 bps (300 ms), Premium is 0.4 bps maker / 2.8 bps taker (200 ms). The market maker is only "0-fee" on a Standard-tier subaccount. `LIGHTER_TIER` in `.env` is for the sniper account.
- **Live news sources**: only adapters in `NEWS_LIVE_SOURCE_ADAPTERS` (default `treenews_ws,webhook,official,x`) or IDs in `NEWS_LIVE_SOURCE_IDS` can open positions. Polled RSS/Google News headlines are recorded as shadow bets on the scoreboard so their edge can be measured before enabling them.
- **Risk caps** (`lighter_news_risk.py`): `NEWS_MAX_EXPOSURE_USD`, `NEWS_MAX_ASSET_EXPOSURE_USD`, `NEWS_MAX_CONCURRENCY`, `NEWS_MAX_GROSS_LEVERAGE` count *open* positions, not just in-flight orders.
- **Exits** (`trade_exits.py`): catalyst-class time stops (Tier-1 listing 240 min, macro 90, partnership 120, other 60). A live position whose exchange TP+SL cannot be attached is flattened (`NEWS_CLOSE_IF_UNPROTECTED=1`).
- **P&L attribution**: every entry/exit lands in `trade_ledger.py`; `/report` and `/attribution [hours]` in Telegram show P&L by source, catalyst type and exit reason.
- **`quant_engines/`** holds ~100 research engines used only by `master_profit_orchestrator.py` telemetry (`/orchestrator`). None of them are on the trade path.

---

## 💾 Disaster Recovery Runbook

A permanent release backup tag is maintained on GitHub:
* **Release Tag**: **`v2.0-stable-production-backup`**
* **Runbook Guide**: [`BACKUP_STRATEGY_RUNBOOK.md`](BACKUP_STRATEGY_RUNBOOK.md) for 1-click strategy restoration anytime.

---

## 🔒 Security & Privacy

* API Keys, Private Keys, and Telegram tokens are strictly handled via encrypted environment variables and local `.env`.
* Zero private keys or credentials are ever exposed in public repos.
