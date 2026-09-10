from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from news_pipeline import NormalizedNewsEvent
from news_quality import quality_veto


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...] = ()
    reservation_id: str = ""
    sized_usd: float = 0.0


@dataclass
class MarketSnapshot:
    asset: str
    price: float
    spread_bps: float = 0.0
    timestamp: float = field(default_factory=time.time)
    depth_usd: float = 0.0
    volatility_bps: float = 0.0
    size_decimals: int = 4
    price_decimals: int = 2
    min_base_amount: float = 0.0
    market_index: int = 0

    @property
    def fresh(self) -> bool:
        max_age = float(os.getenv("NEWS_MAX_PRICE_AGE_SECONDS", "10"))
        return self.price > 0 and time.time() - self.timestamp <= max_age


def _settings_or_none():
    try:
        from settings import get_settings

        return get_settings()
    except Exception:
        return None


def _kill_switch_on() -> bool:
    # Prefer live process env so tests can toggle NEWS_KILL_SWITCH without cache issues.
    if os.getenv("NEWS_KILL_SWITCH", "").lower() in {"1", "true", "yes"}:
        return True
    s = _settings_or_none()
    return bool(s.news_kill_switch) if s is not None else False


def promotion_mode() -> str:
    env = os.getenv("NEWS_PROMOTION_MODE")
    if env is not None and str(env).strip() != "":
        return str(env).strip().lower()
    s = _settings_or_none()
    if s is not None:
        return (s.news_promotion_mode or "live").strip().lower()
    return "live"


def live_execution_allowed(cli_live: bool = True) -> bool:
    """Allow live fills when requested, unless the kill switch is engaged.

    Promotion / paper / dry-run modes do not gate execution — only the kill switch
    and an explicit False live flag block orders.
    """
    if _kill_switch_on():
        return False
    return bool(cli_live)

# =============================================================================
# UPGRADE 5 — Session-Aware Sizing Gate
# =============================================================================
_CRYPTO_SESSION_ASSETS = {
    "BTC","ETH","SOL","HYPE","XRP","DOGE","ADA","AVAX","BNB","LTC",
    "LINK","DOT","XLM","SUI","TRX","ATOM","MATIC","ARB","OP","APT","HYPE"
}
_FX_SESSION_ASSETS = {
    "EURUSD","GBPUSD","USDJPY","AUDUSD","NZDUSD","USDCAD","USDCHF","USDHKD","USDKRW"
}
_COMMODITY_SESSION_ASSETS = {
    "WTI","BRENTOIL","XAU","XAG","XCU","XPT","XPD","NATGAS","WHEAT","PAXG","XAUT"
}


def session_size_multiplier(symbol: str) -> float:
    """
    Returns a sizing multiplier (0.40 – 1.00) based on asset class + current UTC session.
    Equities: full size during NYSE hours 13:30–20:00 UTC (pre-market 0.65x, after-hours 0.45x).
    Commodities: full size during London/NY commodity hours 08:00–17:00 UTC (off-hours 0.55x).
    FX: full size during London+NY overlap 07:00–16:00 UTC (off-hours 0.70x).
    Crypto: always 1.0 (24/7 market, no session penalty).
    Additionally applies a 0.85x diurnal penalty during very low-vol drift windows (vol < 0.75x baseline).
    """
    sym = (symbol or "").upper()
    h = datetime.now(timezone.utc).hour

    if sym in _CRYPTO_SESSION_ASSETS:
        base_mult = 1.0
    elif sym in _FX_SESSION_ASSETS:
        base_mult = 1.0 if 7 <= h <= 16 else 0.70
    elif sym in _COMMODITY_SESSION_ASSETS:
        base_mult = 1.0 if 8 <= h <= 17 else 0.55
    else:
        # Default: treat as equity
        base_mult = 1.0 if 13 <= h <= 20 else (0.65 if 9 <= h < 13 else 0.45)

    # Diurnal vol penalty: if seasonal vol curve indicates very quiet window, reduce further
    try:
        from intraday_seasonality_profile import IntradaySeasonalityProfileEngine
        _diurnal = IntradaySeasonalityProfileEngine().evaluate_current_seasonality(utc_hour=h)
        if _diurnal.diurnal_volatility_multiplier < 0.75:
            base_mult = round(base_mult * 0.85, 4)
    except Exception:
        pass  # Never block on diurnal engine failures

    return round(base_mult, 4)


class LighterNewsRiskGate:
    def __init__(self, live: bool = True) -> None:
        self.live = live
        self.execution_live = live_execution_allowed(live)
        self.max_exposure_usd = float(os.getenv("NEWS_MAX_EXPOSURE_USD", "1000"))
        self.max_trade_usd = float(os.getenv("NEWS_MAX_TRADE_USD", "100"))
        self.max_spread_bps = float(os.getenv("NEWS_MAX_SPREAD_BPS", "100"))
        self.min_confidence = float(os.getenv("NEWS_MIN_CONFIDENCE", "0.70"))
        self.confirmed_only = os.getenv("NEWS_AUTO_TRADE_CONFIRMED_ONLY", "true").lower() == "true"
        self.max_asset_usd = float(os.getenv("NEWS_MAX_ASSET_EXPOSURE_USD", os.getenv("NEWS_MAX_EXPOSURE_USD", "1000")))
        self.max_directional_usd = float(os.getenv("NEWS_MAX_DIRECTIONAL_USD", os.getenv("NEWS_MAX_EXPOSURE_USD", "1000")))
        self.max_daily_loss_usd = float(os.getenv("NEWS_MAX_DAILY_LOSS_USD", "200"))
        self.max_consecutive_losses = int(os.getenv("NEWS_MAX_CONSECUTIVE_LOSSES", "50"))
        self.max_session_trades = int(os.getenv("NEWS_MAX_SESSION_TRADES", "500"))
        self.cooldown_seconds = float(os.getenv("NEWS_ASSET_COOLDOWN_SECONDS", "900"))
        self.risk_per_trade_pct = float(os.getenv("NEWS_RISK_PER_TRADE_PCT", "1.0"))
        max_conc = int(os.getenv("NEWS_MAX_CONCURRENCY", "0"))
        self.max_open_positions = float("inf") if max_conc <= 0 else max_conc
        self.max_gross_leverage = float(os.getenv("NEWS_MAX_GROSS_LEVERAGE", "1.5"))
        self.live_source_ids = {
            source.strip().lower()
            for source in os.getenv("NEWS_LIVE_SOURCE_IDS", "").split(",")
            if source.strip()
        }
        self.live_source_adapters = {
            adapter.strip().lower()
            for adapter in os.getenv("NEWS_LIVE_SOURCE_ADAPTERS", "treenews_ws,webhook,official,x").split(",")
            if adapter.strip()
        }
        self.max_feed_latency_sec = float(os.getenv("NEWS_MAX_FEED_LATENCY_SEC", "20"))
        self._reserved_usd = 0.0
        self._reservations: Dict[str, float] = {}
        self._asset_reserved: Dict[str, float] = {}
        self._directional_reserved: Dict[str, float] = {}
        self._last_asset_trade: Dict[str, float] = {}
        self._open_positions: set[str] = set()
        self._session_trades = 0
        self._consecutive_losses = 0
        self._last_loss_time = 0.0
        self._daily_loss_usd = 0.0
        self._daily_date = ""
        self._pnl_db = os.getenv("NEWS_DB_PATH", "lighter_news.db")
        self._lock = asyncio.Lock()
        self._load_daily_pnl()

    def set_open_position(self, asset: str, is_open: bool = True) -> None:
        sym = (asset or "").upper()
        if sym:
            if is_open:
                self._open_positions.add(sym)
            else:
                self._open_positions.discard(sym)

    def clear_open_position(self, asset: str) -> None:
        self.set_open_position(asset, False)

    def has_open_position(self, asset: str) -> bool:
        return (asset or "").upper() in self._open_positions

    def size_trade(self, requested_usd: float, stop_distance_pct: float, collateral_usd: float) -> float:
        if stop_distance_pct <= 0:
            return min(requested_usd, self.max_trade_usd)
        risk_budget = collateral_usd * (self.risk_per_trade_pct / 100.0)
        sized = risk_budget / (stop_distance_pct / 100.0)
        return round(max(0.0, min(requested_usd, self.max_trade_usd, sized)), 4)

    def source_is_live_eligible(self, event: NormalizedNewsEvent) -> tuple[bool, str]:
        """Return whether an event is sufficiently fast and from a live source."""
        if event.published_at is not None and event.ingested_at is not None:
            latency = (event.ingested_at - event.published_at).total_seconds()
            if latency > self.max_feed_latency_sec:
                return False, f"feed latency {latency:.0f}s exceeds NEWS_MAX_FEED_LATENCY_SEC"

        source_id = (event.source_id or "").lower()
        adapter = str((event.raw or {}).get("adapter", "")).lower()
        allowlists_disabled = not self.live_source_ids and not self.live_source_adapters
        if allowlists_disabled or source_id in self.live_source_ids or adapter in self.live_source_adapters:
            return True, ""
        return False, "source not in live allowlist (shadow only)"

    async def approve(
        self,
        event: Optional[NormalizedNewsEvent],
        snapshot: Optional[MarketSnapshot],
        requested_usd: float,
        confirmed: bool,
        authorized: bool = True,
        asset: str = "",
        side: str = "",
        collateral_usd: Optional[float] = None,
        stop_distance_pct: float = 1.5,
        momentum_confirmed: Optional[bool] = None,
        has_open_position: Optional[bool] = None,
        active_positions: Optional[Dict[str, Any]] = None,
        entry_mode: str = "news",
    ) -> RiskDecision:
        reasons = []
        manual = str(entry_mode or "news").strip().lower() in {"manual", "telegram", "copilot", "strategy"}
        self._roll_day()
        kill_file = os.getenv("NEWS_KILL_SWITCH_FILE", "NEWS_KILL_SWITCH")
        if _kill_switch_on() or os.path.exists(kill_file):
            reasons.append("news kill switch is engaged")
        if self.live and not self.execution_live:
            reasons.append("live execution blocked (kill switch engaged)")
        if requested_usd <= 0:
            reasons.append("trade size exceeds news risk cap")
        if self.live and not authorized:
            reasons.append("live Telegram authorization is not configured")
        if self.live and (snapshot is None or not snapshot.fresh):
            reasons.append("live market price is missing or stale")
        if self.execution_live and collateral_usd is None:
            reasons.append("live collateral query failed")
        if snapshot and snapshot.spread_bps > self.max_spread_bps:
            reasons.append("market spread exceeds news risk cap")
        if snapshot and snapshot.volatility_bps > float(os.getenv("NEWS_MAX_VOL_BPS", "250")):
            reasons.append("volatility shock circuit breaker")
        # Toxic Flow Pre-Trade Veto: Check adverse taker volume ratio
        adverse_taker_ratio = float(getattr(snapshot, "adverse_taker_ratio", 0.0) or 0.0)
        if adverse_taker_ratio >= float(os.getenv("NEWS_MAX_TOXIC_FLOW_RATIO", "0.70")):
            reasons.append(f"toxic order flow veto: adverse taker volume {adverse_taker_ratio*100:.1f}% >= 70%")
        if not manual:
            if event is not None:
                source_eligible, source_reason = self.source_is_live_eligible(event)
                if not source_eligible:
                    reasons.append(source_reason)
            ok, veto_reason = quality_veto(event)
            if not ok:
                reasons.append(veto_reason)
            elif event is not None and event.confidence < self.min_confidence:
                reasons.append("news confidence is below threshold")
            elif event is not None and event.contradiction:
                reasons.append("contradictory news cluster")
            elif event is not None and event.invalidated:
                reasons.append("news cluster was corrected or retracted")
            if self.live and self.confirmed_only and not confirmed:
                reasons.append("news event lacks independent-source confirmation")
        if momentum_confirmed is False:
            if getattr(self, "require_momentum_confirmation", False):
                reasons.append("cross-exchange momentum confirmation failed (no Binance/Bybit volume spike)")
        elif (
            not manual
            and momentum_confirmed is None
            and getattr(self, "momentum_filter", None) is not None
            and event is not None
            and asset
        ):
            try:
                sentiment = "BULLISH" if side.startswith("BUY") else "BEARISH" if side.startswith("SELL") else "NEUTRAL"
                # Only check crypto assets mapped in momentum_filter
                if asset.upper() in getattr(self.momentum_filter, "symbol_map", {}) and event.confidence >= getattr(self.momentum_filter, "high_conviction_threshold", 0.80):
                    m_eval = self.momentum_filter.evaluate_buffer(asset, sentiment)
                    if not m_eval.direction_aligned:
                        reasons.append(f"cross-exchange momentum contradiction on Binance/Bybit for {asset}")
                    elif not m_eval.confirmed and getattr(self.momentum_filter, "require_confirmation", False):
                        reasons.append(f"cross-exchange momentum unconfirmed on Binance/Bybit for {asset}")
            except Exception:
                pass
        if collateral_usd is None:
            sized = min(requested_usd, self.max_trade_usd)
        else:
            sized = self.size_trade(requested_usd, stop_distance_pct, collateral_usd)
        if sized <= 0 or sized > self.max_trade_usd:
            reasons.append("trade size exceeds news risk cap")
        symbol = (asset or (snapshot.asset if snapshot else "")).upper()
        direction = "long" if side.startswith("BUY") else "short" if side.startswith("SELL") else "flat"
        async with self._lock:
            open_notional_total = 0.0
            open_notional_by_asset: Dict[str, float] = {}
            open_notional_by_direction: Dict[str, float] = {"long": 0.0, "short": 0.0}
            open_count = 0
            positions = active_positions.values() if isinstance(active_positions, dict) else (active_positions or ())
            for position in positions:
                def value(name: str, default: Any = None) -> Any:
                    return position.get(name, default) if isinstance(position, dict) else getattr(position, name, default)

                if not value("is_active", True):
                    continue
                notional = abs(float(value("notional_usd", 0.0) or 0.0))
                if notional <= 0:
                    notional = abs(float(value("size_eth", 0.0) or 0.0)) * float(value("entry_price", 0.0) or 0.0)
                position_asset = str(value("asset", value("symbol", "")) or "").upper()
                position_side = str(value("side", "") or "").upper()
                position_direction = "long" if position_side.startswith(("BUY", "LONG")) else "short" if position_side.startswith(("SELL", "SHORT")) else "flat"
                open_count += 1
                open_notional_total += notional
                if position_asset:
                    open_notional_by_asset[position_asset] = open_notional_by_asset.get(position_asset, 0.0) + notional
                if position_direction != "flat":
                    open_notional_by_direction[position_direction] += notional
            if self._session_trades >= self.max_session_trades:
                reasons.append("session trade-count breaker")
            if self._consecutive_losses >= self.max_consecutive_losses:
                reasons.append("consecutive-loss breaker")
            if self._daily_loss_usd >= self.max_daily_loss_usd:
                reasons.append("daily loss breaker")
            last = self._last_asset_trade.get(symbol, 0.0)
            is_open = (
                has_open_position is True
                or (has_open_position is None and self.has_open_position(symbol))
                or bool(active_positions and any(
                    (getattr(p, "asset", p.get("symbol", "") if isinstance(p, dict) else str(p)).upper() == symbol)
                    and getattr(p, "is_active", True)
                    and (abs(getattr(p, "notional_usd", 0.0)) >= 10.0 or abs(getattr(p, "size_eth", 0.0)) * getattr(p, "entry_price", 0.0) >= 10.0)
                    for p in (active_positions.values() if isinstance(active_positions, dict) else active_positions)
                ))
            )
            if symbol and (is_open or (time.time() - last < self.cooldown_seconds)):
                reasons.append("duplicate news signal: active position or cooldown in effect")
            if open_count >= self.max_open_positions:
                reasons.append("max concurrent positions reached")
            if self._reserved_usd + open_notional_total + sized > self.max_exposure_usd:
                reasons.append("aggregate news exposure cap reached")
            if symbol and self._asset_reserved.get(symbol, 0.0) + open_notional_by_asset.get(symbol, 0.0) + sized > self.max_asset_usd:
                reasons.append("per-asset exposure cap reached")
            if direction != "flat" and self._directional_reserved.get(direction, 0.0) + open_notional_by_direction[direction] + sized > self.max_directional_usd:
                reasons.append("directional exposure cap reached")
            if collateral_usd is not None and collateral_usd > 0 and (open_notional_total + self._reserved_usd + sized) / collateral_usd > self.max_gross_leverage:
                reasons.append("gross leverage cap reached")
            if reasons:
                return RiskDecision(False, tuple(reasons), sized_usd=sized)
            reservation_id = f"news_res_{int(time.time() * 1000)}"
            self._reservations[reservation_id] = sized
            self._reserved_usd += sized
            if symbol:
                self._asset_reserved[symbol] = self._asset_reserved.get(symbol, 0.0) + sized
            if direction != "flat":
                self._directional_reserved[direction] = self._directional_reserved.get(direction, 0.0) + sized
            return RiskDecision(True, (), reservation_id, sized)

    def record_fill(self, asset: str) -> None:
        symbol = (asset or "").upper()
        if symbol:
            self._last_asset_trade[symbol] = time.time()
            self._open_positions.add(symbol)
        self._session_trades += 1
        self._save_daily_pnl()

    async def release(self, reservation_id: str, asset: str = "", side: str = "") -> None:
        async with self._lock:
            amount = self._reservations.pop(reservation_id, 0.0)
            self._reserved_usd = max(0.0, self._reserved_usd - amount)
            symbol = asset.upper()
            if symbol:
                self._asset_reserved[symbol] = max(0.0, self._asset_reserved.get(symbol, 0.0) - amount)
            direction = "long" if side.startswith("BUY") else "short" if side.startswith("SELL") else ""
            if direction:
                self._directional_reserved[direction] = max(0.0, self._directional_reserved.get(direction, 0.0) - amount)

    def record_pnl(self, pnl_usd: float) -> None:
        self._roll_day()
        if pnl_usd < -2.0:
            self._consecutive_losses += 1
            self._last_loss_time = time.time()
            self._daily_loss_usd += abs(pnl_usd)
        elif pnl_usd >= 0:
            self._consecutive_losses = 0
        self._save_daily_pnl()

    def reset_loss_breaker(self) -> None:
        self._consecutive_losses = 0
        self._save_daily_pnl()

    def _utc_day(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll_day(self) -> None:
        today = self._utc_day()
        if self._daily_date != today:
            self._daily_date = today
            self._daily_loss_usd = 0.0
            self._consecutive_losses = 0
            self._session_trades = 0
        elif self._consecutive_losses > 0 and time.time() - getattr(self, "_last_loss_time", 0.0) > 900:
            self._consecutive_losses = 0

    def _load_daily_pnl(self) -> None:
        try:
            with sqlite3.connect(self._pnl_db) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS news_daily_pnl (day TEXT PRIMARY KEY, loss_usd REAL NOT NULL, consecutive INTEGER NOT NULL, trades INTEGER NOT NULL, payload TEXT NOT NULL)"
                )
                row = conn.execute("SELECT day, loss_usd, consecutive, trades FROM news_daily_pnl WHERE day = ?", (self._utc_day(),)).fetchone()
            if row:
                self._daily_date, self._daily_loss_usd, self._consecutive_losses, self._session_trades = row[0], float(row[1]), int(row[2]), int(row[3])
            else:
                self._daily_date = self._utc_day()
        except sqlite3.Error:
            self._daily_date = self._utc_day()

    def _save_daily_pnl(self) -> None:
        try:
            with sqlite3.connect(self._pnl_db) as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS news_daily_pnl (day TEXT PRIMARY KEY, loss_usd REAL NOT NULL, consecutive INTEGER NOT NULL, trades INTEGER NOT NULL, payload TEXT NOT NULL)"
                )
                conn.execute(
                    "INSERT OR REPLACE INTO news_daily_pnl VALUES (?, ?, ?, ?, ?)",
                    (
                        self._utc_day(),
                        self._daily_loss_usd,
                        self._consecutive_losses,
                        self._session_trades,
                        json.dumps({"updated": time.time()}),
                    ),
                )
        except sqlite3.Error:
            pass

    def readiness(self, authorized: bool, snapshot: Optional[MarketSnapshot], has_markets: bool) -> tuple[bool, tuple[str, ...]]:
        reasons = []
        if _kill_switch_on():
            reasons.append("kill switch")
        if self.live and not authorized:
            reasons.append("missing telegram authorization")
        if self.live and (snapshot is None or not snapshot.fresh):
            reasons.append("missing or stale market data")
        if not has_markets:
            reasons.append("market registry empty")
        if self.live and not self.execution_live:
            reasons.append("kill switch engaged")
        return (not reasons), tuple(reasons)

    @property
    def reserved_usd(self) -> float:
        return self._reserved_usd
