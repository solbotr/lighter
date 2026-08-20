# Lighter — Upgrade Program

## Tranche 1: upgrades 1–100
Baseline hardening: news normalization, deduplication, entity detection, Lighter market-data interfaces, signal gates, risk limits, and execution safety.

## Tranche 2: upgrades 101–200
Multi-source news intelligence, feed health, source provenance, event clustering, entity/market mapping, and event classifiers.

## Tranche 3: upgrades 201–300

### Market microstructure
201. L2 book normalization
202. L2 sequence validation
203. Snapshot/delta consistency check
204. Missing-update detection
205. Duplicate-update rejection
206. Out-of-order update rejection
207. Book checksum interface
208. Bid-level aggregation
209. Ask-level aggregation
210. Top-N depth metrics
211. Depth imbalance metric
212. Microprice calculation
213. Order-book pressure score
214. Spread percentile
215. Spread regime classification
216. Effective spread estimator
217. Expected slippage curve
218. Market-impact curve
219. Liquidity percentile
220. Liquidity regime classification
221. Trade-tape normalization
222. Trade sequence validation
223. Aggressor-side inference
224. Buy-volume ratio
225. Sell-volume ratio
226. Volume delta
227. Volume acceleration
228. Trade-size distribution
229. Large-trade detector
230. Sweep detector
231. Block-trade flag
232. Wash-trade anomaly flag
233. Price-gap detector
234. Return-window calculator
235. Realized volatility windows
236. EWMA volatility
237. Volatility percentile
238. ATR-like range metric
239. Jump-intensity metric
240. Tail-risk metric
241. Price-volume divergence
242. Order-book/price divergence
243. Momentum persistence score
244. Reversal-pressure score
245. Market-impact decay

### Event reaction engine
246. Event reaction start timestamp
247. Pre-event price baseline
248. Pre-event volume baseline
249. Post-event return windows
250. Post-event volume windows
251. Event-window volatility
252. Abnormal-return estimator
253. Abnormal-volume estimator
254. Reaction velocity
255. Reaction acceleration
256. Peak reaction tracker
257. Peak-to-current retracement
258. First-minute reaction score
259. Five-minute reaction score
260. Fifteen-minute reaction score
261. One-hour reaction score
262. Multi-window agreement
263. Reaction persistence test
264. Reaction exhaustion test
265. Breakout confirmation
266. Failed-breakout detection
267. Gap-fill detection
268. Mean-reversion probability
269. Trend-continuation probability
270. Volatility-expansion probability
271. Volatility-compression probability
272. Event-induced regime transition
273. Market-wide reaction benchmark
274. BTC benchmark reaction
275. ETH benchmark reaction
276. Sector benchmark reaction
277. Relative-strength calculation
278. Relative-volume calculation
279. Cross-market lead/lag
280. Reaction anomaly ranking

### Signal quality
281. Signal component registry
282. Component normalization
283. Component weighting
284. Weight versioning
285. Weight bounds
286. Score range enforcement
287. Confidence calibration interface
288. Probability calibration
289. Reliability tracking
290. Signal attribution
291. Feature contribution logging
292. Missing-feature penalty
293. Stale-feature penalty
294. Contradictory-feature penalty
295. Extreme-feature sanity check
296. Outlier feature clipping
297. Feature winsorization interface
298. Feature freshness metadata
299. Feature provenance metadata
300. Deterministic signal fingerprint

## Safety invariant
Tranche 3 strengthens market-data integrity and event-reaction measurement. It does not authorize live execution or allow a signal to bypass risk controls.
