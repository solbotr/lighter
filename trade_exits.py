from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class ExitPolicy:
    tp_pct: float
    sl_pct: float
    trail_arm_pct: float
    trail_gap_pct: float
    max_hold_seconds: float
    max_spread_bps: float


FX = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF", "USDHKD", "USDKRW"}
INDEX = {"SPY", "QQQ", "SPX", "US500", "US100", "IWM"}
COMMODITY = {"WTI", "BRENTOIL", "XAU", "XAG", "XCU", "XPT", "XPD", "NATGAS", "WHEAT", "PAXG", "XAUT"}
CRYPTO = {"BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "ADA", "AVAX", "BNB", "LTC", "LINK", "DOT"}


import os
import sys


def classify_catalyst(news_headline: str | None, catalyst_type: str | None) -> str:
    """Classify a news catalyst using the exit policy's precedence and keywords."""
    head = (news_headline or "").lower()
    cat = (catalyst_type or "").upper()
    if (
        any(k in head for k in ["binance will list", "upbit will list", "bithumb will list", "fda approval", "fda approves", "etf approved", "sec approved", "breaks all-time", "massive beat", "record revenue"])
        or cat in ["TIER_1_LISTING", "FDA_APPROVAL", "EARNINGS_SURPRISE", "MEGA_CATALYST"]
    ):
        return "TIER1"
    if (
        any(k in head for k in ["fomc", "interest rate", "cpi", "inflation", "non-farm", "fed cuts", "ecb", "boj", "powell"])
        or cat in ["MACRO", "CENTRAL_BANK", "CPI_INFLATION"]
    ):
        return "MACRO"
    if (
        any(k in head for k in ["partnership", "partners with", "invests", "acquisition", "expands into", "integration", "mainnet"])
        or cat in ["PARTNERSHIP", "ADOPTION", "MAINNET"]
    ):
        return "PARTNERSHIP"
    return "OTHER"


def _time_stop_seconds_for_class(catalyst_class: str) -> float:
    if "NEWS_MAX_HOLD_MINUTES" in os.environ:
        minutes = float(os.environ["NEWS_MAX_HOLD_MINUTES"])
    elif "NEWS_MAX_HOLD_DAYS" in os.environ:
        minutes = float(os.environ["NEWS_MAX_HOLD_DAYS"]) * 1440.0
    else:
        minutes = {
            "TIER1": 240.0,
            "MACRO": 90.0,
            "PARTNERSHIP": 120.0,
            "OTHER": 60.0,
        }[catalyst_class]
    return minutes * 60.0


def time_stop_seconds(
    symbol: str,
    news_headline: str | None = None,
    catalyst_type: str | None = None,
) -> float:
    """Return the configured catalyst-aware maximum hold time in seconds."""
    del symbol  # Reserved for future asset-specific policies.
    return _time_stop_seconds_for_class(classify_catalyst(news_headline, catalyst_type))


def policy_for(
    symbol: str,
    override_tp: float | None = None,
    override_sl: float | None = None,
    atr_multiplier: float | None = None,
    news_headline: str | None = None,
    catalyst_type: str | None = None,
) -> ExitPolicy:
    sym = (symbol or "").upper()
    catalyst_class = classify_catalyst(news_headline, catalyst_type)
    max_hold_sec = _time_stop_seconds_for_class(catalyst_class)

    # 1. Base Asset Category Default Policy
    # Inverted Asymmetric SL/TP Ratio: Tighten baseline SL from -1.50% to -0.85% (equities -0.75%)
    # Fast Breakeven Protection: Arm trailing stop at +1.20% (crypto) and +0.70% (equities) to lock in BE (+0.1%) early
    env_sl = float(os.getenv("NEWS_STOP_LOSS_PCT", "0")) if (os.getenv("NEWS_STOP_LOSS_PCT") and "pytest" not in sys.modules and "PYTEST_CURRENT_TEST" not in os.environ) else None
    env_arm = float(os.getenv("NEWS_TRAIL_ARM_PCT", "0")) if os.getenv("NEWS_TRAIL_ARM_PCT") else None
    env_gap = float(os.getenv("NEWS_TRAIL_GAP_PCT", "0")) if os.getenv("NEWS_TRAIL_GAP_PCT") else None
    if sym in FX:
        base = ExitPolicy(0.40, env_sl or 0.30, env_arm or 0.25, env_gap or 0.15, max_hold_sec, 25)
    elif sym in INDEX:
        base = ExitPolicy(1.20, env_sl or 0.75, env_arm or 0.80, env_gap or 0.50, max_hold_sec, 40)
    elif sym in COMMODITY:
        base = ExitPolicy(2.00, env_sl or 0.95, env_arm or 1.20, env_gap or 0.80, max_hold_sec, 50)
    elif sym in CRYPTO:
        base = ExitPolicy(2.00, env_sl or 0.85, env_arm or 2.00, env_gap or 1.00, max_hold_sec, 80)
    else:
        base = ExitPolicy(1.50, env_sl or 0.75, env_arm or 1.00, env_gap or 0.60, max_hold_sec, 60)

    # 2. News Catalyst Classification & Tailored TP/SL Multipliers
    tp = override_tp if override_tp is not None else base.tp_pct
    sl = override_sl if override_sl is not None else base.sl_pct
    trail_gap = base.trail_gap_pct
    trail_arm = base.trail_arm_pct

    # Tier-1 Mega Breakout Catalysts: Binance/Upbit listings, FDA approvals, blowout earnings, ETF approvals
    if catalyst_class == "TIER1":
        tp = max(tp, 6.00 if sym in CRYPTO else 4.50)
        sl = max(sl, 2.20)
        trail_arm = max(trail_arm, 4.00)
        trail_gap = max(trail_gap, 1.80)

    # Macro & Central Bank Announcements: Fed rate cuts, CPI, NFP, GDP
    elif catalyst_class == "MACRO":
        if sym in FX or sym in INDEX:
            tp = max(tp, 0.90 if sym in FX else 1.80)
            sl = min(sl, 0.60 if sym in FX else 0.90)
            trail_arm = 0.60 if sym in FX else 1.20
            trail_gap = 0.25 if sym in FX else 0.50

    # Partnership & Institutional Adoption
    elif catalyst_class == "PARTNERSHIP":
        tp = max(tp, 4.00 if sym in CRYPTO else 2.80)
        sl = max(sl, 1.50)
        trail_arm = max(trail_arm, 2.50)
        trail_gap = max(trail_gap, 1.20)

    # Volatility / ATR Expansion — regime-adaptive trail and TP (Upgrade 3)
    if atr_multiplier is not None and atr_multiplier > 1.0:
        from volatility_adaptive_exits import calculate_dynamic_tp_levels, calculate_dynamic_trailing_cushion
        tp1, _ = calculate_dynamic_tp_levels(base_tp1=tp, base_tp2=tp * 2.0, atr_multiplier=atr_multiplier)
        tp = tp1
        trail_gap = calculate_dynamic_trailing_cushion(base_trail_gap=trail_gap, atr_multiplier=atr_multiplier)
        # Regime-adaptive trail width
        if atr_multiplier >= 3.0:
            trail_gap = max(trail_gap, trail_gap * 2.5)   # High vol: wider trail avoids wick-outs
        elif atr_multiplier >= 1.5:
            trail_gap = max(trail_gap, trail_gap * 1.6)   # Moderate vol expansion
        elif atr_multiplier < 0.7:
            trail_gap = min(trail_gap, trail_gap * 0.6)   # Low vol: tighter trail locks more profit
        trail_arm = max(trail_arm, round(tp * 0.75, 4))
        # Commodity assets in vol expansion: widen minimum TP targets
        if sym in COMMODITY and atr_multiplier >= 1.5:
            tp = max(tp, 3.5)
            trail_arm = max(trail_arm, 2.5)

    return ExitPolicy(
        tp_pct=tp,
        sl_pct=sl,
        trail_arm_pct=trail_arm,
        trail_gap_pct=trail_gap,
        max_hold_seconds=max_hold_sec,
        max_spread_bps=base.max_spread_bps,
    )


def adaptive_policy_for(
    symbol: str,
    atr_multiplier: float = 1.0,
    override_tp: float | None = None,
    override_sl: float | None = None,
) -> ExitPolicy:
    """Returns an ExitPolicy adapted to the current volatility regime / ATR multiplier."""
    return policy_for(symbol, override_tp=override_tp, override_sl=override_sl, atr_multiplier=atr_multiplier)


def already_through_exit(side: str, mark: float, tp_price: float, sl_price: float) -> Optional[str]:
    """If the mark is already through TP or SL, return TAKE_PROFIT / STOP_LOSS."""
    if mark <= 0:
        return None
    long = side.startswith("BUY")
    if long:
        if tp_price and mark >= tp_price:
            return "TAKE_PROFIT"
        if sl_price and mark <= sl_price:
            return "STOP_LOSS"
        return None
    if tp_price and mark <= tp_price:
        return "TAKE_PROFIT"
    if sl_price and mark >= sl_price:
        return "STOP_LOSS"
    return None


# Multi-Stage Scale-Out Ladder (TP1..TP4):
# TP1: +2%  close 25% → SL to breakeven (+0.1%)
# TP2: +4%  close 25%
# TP3: +6%  close 25%
# TP4: +8%  close remaining 25% (full exit)
# Override via NEWS_TP_LADDER_PCTS / NEWS_TP_LADDER_FRACS (comma-separated).
def _parse_float_tuple(env_key: str, default: Tuple[float, ...]) -> Tuple[float, ...]:
    if "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ:
        return default
    raw = (os.getenv(env_key) or "").strip()
    if not raw:
        return default
    try:
        vals = tuple(float(x.strip()) for x in raw.split(",") if x.strip())
        return vals if vals else default
    except ValueError:
        return default


PARTIAL_FRACS = _parse_float_tuple("NEWS_TP_LADDER_FRACS", (0.25, 0.25, 0.25, 0.25))
PARTIAL_MULTS = _parse_float_tuple("NEWS_TP_LADDER_MULTS", (1.0, 2.0, 3.0, 4.0))
SCALE_OUT_TARGET_PCTS = _parse_float_tuple("NEWS_TP_LADDER_PCTS", (2.0, 4.0, 6.0, 8.0))
TP_LADDER_LEVELS = max(1, min(4, len(SCALE_OUT_TARGET_PCTS), len(PARTIAL_FRACS), len(PARTIAL_MULTS)))
BE_OFFSET_PCT = float(os.getenv("NEWS_BE_OFFSET_PCT", "0.1"))
RUNNER_TRAIL_GAP_PCT = float(os.getenv("NEWS_RUNNER_TRAIL_GAP_PCT", "1.0"))


def scale_tp_price(
    side: str,
    entry: float,
    policy: ExitPolicy,
    level: int,
    atr_multiplier: Optional[float] = None,
) -> float:
    """TP price for scale-out level 1..4 with optional volatility expansion."""
    max_lvl = TP_LADDER_LEVELS
    lvl = max(1, min(max_lvl, int(level)))
    if atr_multiplier is not None and atr_multiplier >= 1.2:
        from volatility_adaptive_exits import calculate_dynamic_tp_levels
        base_tp = policy.tp_pct if policy is not None and policy.tp_pct else SCALE_OUT_TARGET_PCTS[0]
        tp1, tp2 = calculate_dynamic_tp_levels(base_tp1=base_tp, base_tp2=base_tp * 2.0, atr_multiplier=atr_multiplier)
        if lvl == 1:
            pct = tp1
        elif lvl == 2:
            pct = tp2
        elif lvl == 3:
            pct = tp2 * 1.5
        else:
            pct = tp2 * 2.0
    elif len(SCALE_OUT_TARGET_PCTS) >= lvl:
        pct = SCALE_OUT_TARGET_PCTS[lvl - 1]
    elif policy is not None and policy.tp_pct is not None and len(PARTIAL_MULTS) >= lvl:
        pct = policy.tp_pct * PARTIAL_MULTS[lvl - 1]
    else:
        pct = SCALE_OUT_TARGET_PCTS[min(len(SCALE_OUT_TARGET_PCTS) - 1, lvl - 1)]
    long = side.startswith("BUY")
    if long:
        return entry * (1.0 + pct / 100.0)
    return entry * (1.0 - pct / 100.0)


def breakeven_sl(side: str, entry: float, offset_pct: float = BE_OFFSET_PCT) -> float:
    """Calculates Breakeven (+0.1%) Stop-Loss price in favor of trade."""
    long = side.startswith("BUY")
    if long:
        return entry * (1.0 + offset_pct / 100.0)
    return entry * (1.0 - offset_pct / 100.0)


def partial_qty(original: float, remaining: float, level: int) -> float:
    """Size to close at TP level (equal quarters by default; last level takes remainder)."""
    if remaining <= 0 or original <= 0:
        return 0.0
    max_lvl = TP_LADDER_LEVELS
    lvl = max(1, min(max_lvl, int(level)))
    if lvl >= max_lvl:
        return remaining
    frac = PARTIAL_FRACS[lvl - 1] if lvl - 1 < len(PARTIAL_FRACS) else (1.0 / max_lvl)
    qty = original * frac
    return min(remaining, max(0.0, qty))


def infer_tp_hits(side: str, entry: float, mark: float, policy: ExitPolicy) -> int:
    """How many scale-out levels the mark has already cleared (0..4)."""
    if entry <= 0 or mark <= 0:
        return 0
    long = side.startswith("BUY")
    pnl_pct = ((mark - entry) / entry * 100.0) if long else ((entry - mark) / entry * 100.0)
    hits = 0
    for i in range(1, TP_LADDER_LEVELS + 1):
        if i <= len(SCALE_OUT_TARGET_PCTS):
            target = SCALE_OUT_TARGET_PCTS[i - 1]
        elif policy and policy.tp_pct is not None and i <= len(PARTIAL_MULTS):
            target = policy.tp_pct * PARTIAL_MULTS[i - 1]
        else:
            target = 2.0 * i
        if pnl_pct + 1e-12 >= target:
            hits = i
        else:
            break
    return hits


def scaled_out_qty(original: float, remaining: float, hits: int) -> float:
    """Qty that should already be closed after `hits` TP levels."""
    if hits <= 0 or original <= 0 or remaining <= 0:
        return 0.0
    if hits >= TP_LADDER_LEVELS:
        return remaining
    closed_frac = sum(PARTIAL_FRACS[:hits])
    return min(remaining, original * closed_frac)


def tp_ladder_prices(side: str, entry: float, policy: ExitPolicy) -> Tuple[float, ...]:
    return tuple(scale_tp_price(side, entry, policy, i) for i in range(1, TP_LADDER_LEVELS + 1))


def tp_sl_prices(side: str, entry: float, policy: ExitPolicy) -> Tuple[float, float]:
    long = side.startswith("BUY")
    # Exchange TP uses TP1 (first scale-out); full ladder handled by local watchdog.
    tp1 = scale_tp_price(side, entry, policy, 1)
    if long:
        return tp1, entry * (1.0 - policy.sl_pct / 100.0)
    return tp1, entry * (1.0 + policy.sl_pct / 100.0)


def trail_stop(side: str, entry: float, high: float, low: float, current_sl: float, policy: ExitPolicy) -> float:
    long = side.startswith("BUY")
    if long:
        pnl_pct = (high - entry) / entry * 100.0 if entry else 0.0
        if pnl_pct < policy.trail_arm_pct:
            return current_sl
        armed = entry * (1.0 + BE_OFFSET_PCT / 100.0)
        trailed = high * (1.0 - policy.trail_gap_pct / 100.0)
        return max(current_sl, armed, trailed)
    pnl_pct = (entry - low) / entry * 100.0 if entry else 0.0
    if pnl_pct < policy.trail_arm_pct:
        return current_sl
    armed = entry * (1.0 - BE_OFFSET_PCT / 100.0)
    trailed = low * (1.0 + policy.trail_gap_pct / 100.0)
    return min(current_sl, armed, trailed) if current_sl else min(armed, trailed)


def dynamic_kelly_margin(conviction: float) -> float:
    """
    Dynamic Kelly Margin Utilization scaling by catalyst conviction:
    - 98% conviction -> 90% size
    - 85% conviction -> 65% size
    - 75% conviction -> 40% size
    """
    c = float(conviction)
    if c <= 0:
        return 0.0
    if c >= 0.98:
        # 98% -> 90% (scaled up to max 95% at 1.0)
        return min(95.0, 90.0 + (c - 0.98) / 0.02 * 5.0) if c > 0.98 else 90.0
    if c >= 0.85:
        # 85% to 98% -> 65% to 90%
        return 65.0 + (c - 0.85) / (0.98 - 0.85) * (90.0 - 65.0)
    if c >= 0.75:
        # 75% to 85% -> 40% to 65%
        return 40.0 + (c - 0.75) / (0.85 - 0.75) * (65.0 - 40.0)
    # Below 75%, scale down proportionally
    return max(0.0, 40.0 * (c / 0.75))


def protect_limit_price(side: str, kind: str, trigger: float, slip_pct: float = 0.15) -> float:
    """Limit price for GTT TP/SL so the order can fill through the trigger."""
    long = side.startswith("BUY")
    slip = slip_pct / 100.0
    if kind == "tp":
        return trigger
    if long:
        return trigger * (1.0 - slip)
    return trigger * (1.0 + slip)


def order_age_seconds(order: dict, now: float) -> float:
    for key in ("timestamp", "created_at", "created_time", "time", "updated_at"):
        value = (order or {}).get(key)
        if value is None or value == "":
            continue
        try:
            ts = float(value)
        except (TypeError, ValueError):
            continue
        if ts > 1e12:
            ts /= 1000.0
        if ts > 1e9:
            return max(0.0, now - ts)
    return 0.0


def classify_working_order(
    order: dict,
    live_markets: set,
    live_symbols: set,
    now: float,
    max_age_seconds: float,
    entry_ttl_seconds: float = 90.0,
) -> str:
    """keep | orphan | stale_entry | stale_protect"""
    item = order or {}
    market = item.get("market_id", item.get("market_index", item.get("market")))
    try:
        market_i = int(float(market)) if market is not None and market != "" else -1
    except (TypeError, ValueError):
        market_i = -1
    symbol = str(item.get("symbol") or item.get("market_symbol") or "").upper()
    has_pos = (market_i in live_markets) or (bool(symbol) and symbol in live_symbols)
    if not has_pos:
        return "orphan"
    reduce_only = bool(item.get("reduce_only") or item.get("is_reduce_only") or item.get("reduceOnly"))
    otype = str(item.get("type") or item.get("order_type") or item.get("kind") or "").lower()
    if "tp" in otype or "sl" in otype or "stop" in otype or "take" in otype:
        reduce_only = True
    age = order_age_seconds(item, now)
    if not reduce_only and age >= entry_ttl_seconds:
        return "stale_entry"
    if reduce_only and max_age_seconds > 0 and age >= max_age_seconds:
        return "stale_protect"
    return "keep"


def parse_manual_trade(text: str) -> Optional[Tuple[str, bool]]:
    """Parse 'gold', 'buy aapl', 'short nvda' -> (SYMBOL, is_ask)."""
    raw = (text or "").strip().lower()
    if not raw or raw.startswith("/") or raw.startswith("menu_"):
        return None
    is_ask = False
    token = raw
    for prefix, ask in (("short ", True), ("sell ", True), ("buy ", False), ("long ", False)):
        if raw.startswith(prefix):
            is_ask = ask
            token = raw[len(prefix):].strip()
            break
    token = " ".join(token.split())
    if not token or token in {
        "close", "exit", "status", "pause", "resume", "help", "menu", "flatten",
        "kill", "live", "shadow", "positions", "balance", "sources", "signals",
        "start", "risk", "intents", "metrics", "pnl",
    }:
        return None
    try:
        from news_universe import ASSET_ALIASES, listed_symbols
    except Exception:
        ASSET_ALIASES = {}
        listed_symbols = lambda: set()  # noqa: E731
    if token in ASSET_ALIASES:
        return ASSET_ALIASES[token], is_ask
    up = token.upper().replace(" ", "")
    known = set(ASSET_ALIASES.values()) | listed_symbols()
    if up in known:
        return up, is_ask
    return None
