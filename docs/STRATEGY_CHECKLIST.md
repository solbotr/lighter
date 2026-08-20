# Strategy Checklist

## Before a signal
- Is the source credible?
- Is the event genuinely new?
- Is the asset relationship explicit?
- Is the information available at the decision timestamp?
- Are independent sources consistent?
- Has the market already repriced?
- Is there a concurrent market-wide catalyst?

## Before an order
- Is the signal still fresh?
- Is liquidity sufficient?
- Is expected slippage acceptable?
- Are fees and funding acceptable?
- Does the order pass portfolio risk?
- Does it pass leverage and margin limits?
- Is the market state current?
- Is the account state current?
- Is the order idempotent?
- Is the kill switch clear?

## After an order
- Was acknowledgement received?
- Were fills reconciled?
- Does position state match exchange state?
- Does realized/unrealized PnL reconcile?
- Is the event-to-trade audit trail complete?
