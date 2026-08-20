# Lighter — Upgrade Program

## Tranche 1: upgrades 1–100
Baseline hardening: news normalization, deduplication, entity detection, Lighter market-data interfaces, signal gates, risk limits, and execution safety.

## Tranche 2: upgrades 101–200
Multi-source news intelligence, feed health, source provenance, event clustering, entity/market mapping, and event classifiers.

## Tranche 3: upgrades 201–300
Market microstructure, event reaction measurement, feature quality and deterministic signal fingerprints.

## Tranche 4: upgrades 301–400

### Backtesting and research
301. Event replay clock
302. Deterministic replay mode
303. Historical news schema
304. Historical market-data schema
305. Point-in-time entity mapping
306. Point-in-time source scores
307. Point-in-time market metadata
308. Look-ahead-bias detector
309. Survivorship-bias guard
310. Delisted-market handling
311. Missing-data accounting
312. Gap-aware replay
313. Feed-latency simulation
314. Execution-latency simulation
315. Order-book snapshot replay
316. Trade-tape replay
317. Slippage simulation
318. Fee simulation
319. Funding simulation
320. Borrow/carry cost interface
321. Partial-fill simulation
322. Cancel/replace simulation
323. Rejected-order simulation
324. Network-failure simulation
325. Exchange-outage simulation
326. Signal-expiry replay
327. Risk-limit replay
328. Kill-switch replay
329. Daily-reset replay
330. Position-state reconstruction
331. Balance-state reconstruction
332. PnL reconstruction
333. Realized/unrealized PnL separation
334. Mark-price policy
335. Benchmark-return calculation
336. Event-window attribution
337. Trade attribution
338. Signal attribution
339. Source attribution
340. Strategy attribution
341. Fee-adjusted return
342. Slippage-adjusted return
343. Risk-adjusted return
344. Maximum drawdown
345. Calmar ratio
346. Sharpe-like metric
347. Sortino-like metric
348. Profit factor
349. Expectancy
350. Win-rate confidence interval

### Validation and robustness
351. Walk-forward splits
352. Purged time-series splits
353. Embargo periods
354. Parameter-free baseline
355. Buy-and-hold benchmark
356. Event-naive benchmark
357. Random-entry benchmark
358. Source-ablation test
359. Feature-ablation test
360. Market-ablation test
361. Latency-ablation test
362. Slippage-ablation test
363. Fee-ablation test
364. Risk-limit-ablation test
365. Threshold sensitivity sweep
366. Freshness sensitivity sweep
367. Source-weight sensitivity sweep
368. Market-confirmation sensitivity sweep
369. Already-priced-in sensitivity sweep
370. Position-size sensitivity sweep
371. Leverage sensitivity sweep
372. Stop-policy sensitivity sweep
373. Take-profit sensitivity sweep
374. Cooldown sensitivity sweep
375. Holding-period sensitivity sweep
376. Regime sensitivity sweep
377. Monte Carlo trade-order shuffle
378. Bootstrap return confidence
379. Bootstrap drawdown confidence
380. Worst-case slippage scenario
381. Worst-case latency scenario
382. Feed-outage scenario
383. Duplicate-news scenario
384. Contradictory-news scenario
385. Rumor scenario
386. Retraction scenario
387. Correction scenario
388. Market-crash scenario
389. Flash-move scenario
390. Low-liquidity scenario
391. High-volatility scenario
392. Correlated-position scenario
393. API-error scenario
394. Clock-skew scenario
395. Restart-recovery scenario
396. State-corruption scenario
397. Partial-data scenario
398. Unknown-event scenario
399. Out-of-distribution-event scenario
400. Research reproducibility manifest

## Safety invariant
Tranche 4 improves research integrity and prevents backtests from overstating an edge. Historical results must include realistic latency, fees, slippage, missing data, and risk constraints. Live execution remains opt-in.
