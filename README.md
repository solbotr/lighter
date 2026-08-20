# Lighter

News-driven automated crypto trading system.

## Vision

Lighter monitors high-impact news, identifies affected crypto assets, estimates the likely market impact, and turns validated signals into risk-controlled trading decisions.

A core use case is **headline-to-price reaction**: when a major public figure, institution, regulator, exchange, protocol, or company makes a market-relevant statement, Lighter should detect the event quickly, determine which assets are exposed, and evaluate whether the move is actionable or already priced in.

## Pipeline

```text
News Sources
    ↓
Ingestion & Deduplication
    ↓
Entity / Asset Detection
    ↓
Source Credibility
    ↓
Event Classification
    ↓
Sentiment + Market Impact Score
    ↓
Price / Volume Confirmation
    ↓
Latency & Already-Priced-In Check
    ↓
Risk Engine
    ↓
Paper Trading
    ↓
Execution Adapter
```

## Safety-first development

- Paper trading by default
- No trading from a single unverified source
- Duplicate and stale-news rejection
- Position, leverage, exposure, and drawdown limits
- Kill switch
- Full signal and execution audit trail
- Explicit separation between signal generation and order execution
- Exchange/API failures fail closed

## Planned modules

- `news/` — feed ingestion, normalization, deduplication
- `signals/` — event extraction and market-impact scoring
- `market/` — price, volume, volatility and liquidity confirmation
- `risk/` — sizing, exposure, leverage and drawdown controls
- `execution/` — exchange adapters and order lifecycle
- `backtest/` — historical event replay and evaluation
- `storage/` — events, signals, trades and metrics
- `tests/` — unit, integration and replay tests

## Initial strategy concept

A headline is not automatically a trade. Lighter should require a combination of:

1. Credible source
2. Clear asset/entity relationship
3. Materiality of the event
4. Freshness of the information
5. Confirming market reaction
6. Sufficient liquidity
7. Acceptable expected edge after fees/slippage
8. Risk limits passing

The system should also explicitly model **sell-the-news**, delayed reactions, contradictory headlines, rumor cascades, and cases where the market has already moved before the signal reaches the executor.

## Status

Early-stage architecture. Paper trading and historical replay come before live execution.
