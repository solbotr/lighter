# Lighter — Upgrade Program

## Tranches 1–3: upgrades 1–300
Completed tracker coverage for baseline hardening, news intelligence, entity mapping, market microstructure, event reaction measurement, and signal-quality controls.

## Tranche 4: upgrades 301–400

### Backtesting integrity
301. Event-time replay clock
302. Point-in-time news store
303. Point-in-time market store
304. Look-ahead-bias guard
305. Future-data access assertion
306. Survivorship-bias guard
307. Delisted-market retention
308. Symbol-history mapping
309. Historical alias versioning
310. Historical source availability tracking
311. News-ingestion latency replay
312. Market-data latency replay
313. Execution-latency replay
314. Network-delay model
315. Jitter model
316. Order acknowledgement delay model
317. Partial-fill simulation
318. Reject simulation
319. Cancel simulation
320. Cancel/replace simulation
321. Fee model
322. Maker/taker fee model
323. Funding-cost model
324. Borrow-cost model interface
325. Slippage model
326. Spread-cost model
327. Market-impact model
328. Liquidity depletion model
329. Price-gap simulation
330. Flash-move simulation
331. Exchange-outage simulation
332. Feed-outage simulation
333. Stale-price simulation
334. Stale-news simulation
335. Duplicate-news replay
336. Contradictory-news replay
337. Rumor replay
338. Retraction replay
339. Correction replay
340. Delayed-source replay

### Statistical validation
341. Trade-level PnL attribution
342. Event-level PnL attribution
343. Source-level PnL attribution
344. Asset-level PnL attribution
345. Direction-level attribution
346. Holding-time attribution
347. Entry-latency attribution
348. Exit-latency attribution
349. Slippage attribution
350. Fee attribution
351. Funding attribution
352. Gross-return metric
353. Net-return metric
354. Expectancy metric
355. Profit-factor metric
356. Sharpe metric
357. Sortino metric
358. Calmar metric
359. Maximum-drawdown metric
360. Recovery-factor metric
361. Win-rate metric
362. Loss-streak metric
363. Tail-loss metric
364. Tail-gain metric
365. Value-at-risk interface
366. Expected-shortfall interface
367. Bootstrap confidence interval
368. Monte-Carlo trade-order test
369. Parameter sensitivity sweep
370. Threshold sensitivity sweep
371. Latency sensitivity sweep
372. Slippage sensitivity sweep
373. Fee sensitivity sweep
374. News-quality sensitivity sweep
375. Source-ablation test
376. Feature-ablation test
377. Signal-component ablation
378. Randomized-label sanity test
379. No-news baseline
380. Price-only baseline
381. Sentiment-only baseline
382. Momentum-only baseline
383. Buy-and-hold benchmark
384. Random-entry benchmark
385. Market-beta benchmark
386. Out-of-sample holdout
387. Walk-forward split
388. Purged time-series split
389. Embargo window
390. Regime-stratified validation
391. Bull-market validation
392. Bear-market validation
393. Sideways-market validation
394. High-volatility validation
395. Low-volatility validation
396. High-liquidity validation
397. Low-liquidity validation
398. Out-of-distribution event test
399. Reproducibility manifest
400. Backtest result checksum

## Safety invariant
Backtesting must never create live orders. Historical results are evidence for evaluation, not permission to trade live.
