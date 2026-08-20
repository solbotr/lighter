# Lighter — Upgrade Program

## Tranche 1: 100 upgrades

This tranche hardens the news-driven Lighter trading architecture without enabling live trading by default.

### Signal / news
1. Canonical news schema
2. Source identifier normalization
3. Publisher credibility field
4. Publication timestamp validation
5. Ingestion timestamp
6. Source latency measurement
7. Headline normalization
8. Body normalization
9. Duplicate headline detection
10. Near-duplicate detection
11. Event ID generation
12. Entity extraction interface
13. Asset alias registry
14. Ticker normalization
15. Symbol confidence score
16. Country/entity mapping
17. Event-type taxonomy
18. Sentiment score bounds
19. Direction confidence
20. Surprise score
21. Freshness decay
22. Source agreement score
23. Contradiction detection
24. Rumor flag
25. Correction flag
26. Retraction handling
27. Article revision handling
28. Paywall metadata
29. Missing-content handling
30. Unicode-safe normalization

### Market intelligence
31. Lighter market discovery
32. Market metadata cache
33. Tick stream adapter
34. Order-book snapshot adapter
35. Order-book delta adapter
36. Best-bid tracking
37. Best-ask tracking
38. Mid-price calculation
39. Spread calculation
40. Spread guard
41. Depth calculation
42. Slippage estimator
43. Volatility estimator
44. Volume anomaly detector
45. Price-jump detector
46. Price-impact estimator
47. Market freshness guard
48. Stale-book guard
49. Cross-source price validation
50. Signal/price timestamp alignment

### Strategy
51. Event-to-signal interface
52. Signal lifecycle states
53. Signal expiry
54. Minimum confidence threshold
55. Minimum surprise threshold
56. Already-priced-in penalty
57. Momentum confirmation
58. Mean-reversion veto
59. Volatility veto
60. Liquidity veto
61. Conflicting-signal veto
62. Duplicate-trade suppression
63. Cooldown window
64. Per-asset signal limit
65. Global signal limit
66. Position-aware signal scoring
67. Exposure-aware scoring
68. Correlation-aware scoring
69. Market-regime flag
70. Regime-dependent thresholds

### Risk
71. Global kill switch
72. Per-market kill switch
73. Maximum position size
74. Maximum notional exposure
75. Maximum leverage
76. Maximum daily loss
77. Maximum consecutive losses
78. Maximum open positions
79. Maximum order rate
80. Maximum cancel rate
81. Drawdown circuit breaker
82. Volatility circuit breaker
83. Spread circuit breaker
84. Liquidity circuit breaker
85. API-error circuit breaker
86. Clock-skew guard
87. Stale-signal guard
88. Stale-account guard
89. Balance sanity check
90. Available-margin sanity check

### Execution
91. Lighter signer adapter
92. Order-intent schema
93. Client order ID generation
94. Idempotent submission
95. Request timeout
96. Retry classification
97. Exponential backoff
98. Retry jitter
99. Order acknowledgement validation
100. Execution audit record

## Safety invariant
Live execution remains explicitly opt-in. No upgrade in this tranche should bypass risk controls or silently enable live orders.
