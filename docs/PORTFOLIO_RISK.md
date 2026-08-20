# Portfolio Risk Controls

Portfolio decisions must be evaluated globally, not one signal at a time.

## Required controls

- Gross exposure limit
- Net directional exposure limit
- Per-asset exposure limit
- Per-sector exposure limit
- Correlated-asset exposure limit
- Maximum leverage
- Margin utilization ceiling
- Available-margin floor
- Concentration penalty
- Correlation-aware sizing
- Volatility-aware sizing
- Liquidity-aware sizing
- Slippage-aware sizing
- Fee-aware sizing
- Funding-aware sizing
- Drawdown-aware sizing
- Daily-loss stop
- Consecutive-loss stop
- Maximum open positions
- Maximum order rate
- Maximum turnover
- Emergency flatten policy

## Correlation controls

Highly correlated positions should consume shared risk budget. A new position must be rejected or reduced when its marginal portfolio risk exceeds the configured budget, even if the individual signal passes.

## Capital safety

Strategy output must never determine position size without passing through the independent risk engine. Risk limits are upper bounds, not targets.
