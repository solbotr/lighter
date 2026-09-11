from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

# Explicit name -> Lighter symbol. Keep aliases unique enough to avoid English collisions.
ASSET_ALIASES: Dict[str, str] = {
    # crypto
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "ether": "ETH",
    "solana": "SOL",
    "hyperliquid": "HYPE",
    "ripple": "XRP",
    "dogecoin": "DOGE",
    "cardano": "ADA",
    "avalanche": "AVAX",
    "binance coin": "BNB",
    "litecoin": "LTC",
    "chainlink": "LINK",
    "polkadot": "DOT",
    "sui network": "SUI",
    "aptos": "APT",
    "berachain": "BERA",
    "ethena": "ENA",
    "ethena labs": "ENA",
    "near protocol": "NEAR",
    "injective": "INJ",
    "uniswap": "UNI",
    "aave": "AAVE",
    "curve dao": "CRV",
    "curve finance": "CRV",
    "bittensor": "TAO",
    "worldcoin": "WLD",
    "tron": "TRX",
    "shiba inu": "SHIB",
    "floki inu": "FLOKI",
    "bonk": "BONK",
    "dogwifhat": "WIF",
    "pepe": "PEPE",
    "arbitrum": "ARB",
    "optimism": "OP",
    "sei network": "SEI",
    "celestia": "TIA",
    "monad": "MON",
    "zksync": "ZK",
    "layerzero": "ZRO",
    "pyth network": "PYTH",
    "jito": "JTO",
    "jupiter": "JUP",
    "eigenlayer": "EIGEN",
    "pendle": "PENDLE",
    "morpho": "MORPHO",
    "useless": "USELESS",
    # mega-cap equity
    "apple": "AAPL",
    "microsoft": "MSFT",
    "amazon": "AMZN",
    "nvidia": "NVDA",
    "tesla": "TSLA",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "meta platforms": "META",
    "facebook": "META",
    "broadcom": "AVGO",
    "snowflake": "SNOW",    # Fix: SNOW missed on earnings (Upgrade 1 entity patch)
    "snow": "SNOW",
    "intel": "INTC",
    "amd": "AMD",
    "advanced micro devices": "AMD",
    "oracle": "ORCL",
    "palantir": "PLTR",
    "coinbase": "COIN",
    "robinhood": "HOOD",
    "microstrategy": "MSTR",
    "strategy": "MSTR",
    "alibaba": "BABA",
    "tsmc": "TSM",
    "taiwan semiconductor": "TSM",
    "asml": "ASML",
    "samsung": "SAMSUNGUSD",
    "hyundai": "HYUNDAIUSD",
    "tencent": "TENCENT",
    "xiaomi": "XIAOMI",
    "byd": "BYD",
    "nokia": "NOK",
    "ibm": "IBM",
    "dell": "DELL",
    "qualcomm": "QCOM",
    "micron": "MU",
    "arm holdings": "ARM",
    "gamestop": "GME",
    "moderna": "MRNA",
    "openai": "OPENAI",
    "anthropic": "ANTHROPIC",
    "spacex": "SPCX",
    # fx
    "eurusd": "EURUSD",
    "eur": "EURUSD",
    "euro dollar": "EURUSD",
    "euro": "EURUSD",
    "gbpusd": "GBPUSD",
    "gbp": "GBPUSD",
    "sterling": "GBPUSD",
    "cable": "GBPUSD",
    "british pound": "GBPUSD",
    "usdjpy": "USDJPY",
    "jpy": "USDJPY",
    "yen": "USDJPY",
    "japanese yen": "USDJPY",
    "audusd": "AUDUSD",
    "aud": "AUDUSD",
    "australian dollar": "AUDUSD",
    "nzdusd": "NZDUSD",
    "nzd": "NZDUSD",
    "kiwi": "NZDUSD",
    "usdcad": "USDCAD",
    "cad": "USDCAD",
    "loonie": "USDCAD",
    "canadian dollar": "USDCAD",
    "usdchf": "USDCHF",
    "chf": "USDCHF",
    "swiss franc": "USDCHF",
    "usdhkd": "USDHKD",
    "hong kong dollar": "USDHKD",
    "usdkrw": "USDKRW",
    "korean won": "USDKRW",
    # commodities / rwa
    "gold": "XAU",
    "spot gold": "XAU",
    "silver": "XAG",
    "copper": "XCU",
    "oil": "WTI",
    "crude oil": "WTI",
    "crude": "WTI",
    "wti": "WTI",
    "brent": "BRENTOIL",
    "brent oil": "BRENTOIL",
    "strait of hormuz": "WTI",
    "natural gas": "NATGAS",
    "natgas": "NATGAS",
    "wheat": "WHEAT",
    "platinum": "XPT",
    "palladium": "XPD",
    "pax gold": "PAXG",
    "xaut": "XAUT",
    "tether gold": "XAUT",
    "tethergold": "XAUT",
    "xau tether": "XAUT",
    "gold token": "XAUT",
    # indices / rates
    "s&p 500": "SPY",
    "s&p": "SPY",
    "sp500": "SPY",
    "spy": "SPY",
    "us500": "SPY",
    "nasdaq 100": "QQQ",
    "nasdaq-100": "QQQ",
    "nasdaq100": "QQQ",
    "qqq": "QQQ",
    "us100": "QQQ",
    "russell 2000": "IWM",
    "us 10-year": "US10Y",
    "10-year treasury": "US10Y",
    "treasury yield": "US10Y",
    # distinctive names only — never alias the English word "virtual"
    "virtuals": "VIRTUAL",
    "virtuals protocol": "VIRTUAL",
    "virtual protocol": "VIRTUAL",
}

_LISTED: Set[str] = set(ASSET_ALIASES.values())
# Tickers that are also ordinary English. Matching the lowercase word is banned;
# only $TICKER, ALL-CAPS ticker, or a distinctive multi-word alias may trade.
_AMBIGUOUS = {
    "S", "BE", "CC", "MU", "NOW", "BOT", "CAP", "SKY", "MET", "LIT", "EDGE",
    "DATA", "OPEN", "RAIL", "CHIP", "ALL", "NEW", "LOW", "TOP", "BIG", "ONE",
    "FOR", "THE", "AND", "ARE", "YOU", "NOT", "OUT", "CAN", "HAS", "WAS",
    "VIRTUAL", "RIVER", "PROVE", "PUMP", "GRASS", "MEGA", "LITE", "CORE",
    "LINE", "CASH", "POP", "MON", "ARC", "BIO", "FOLKS", "GRAM", "AERO",
    "TRUE", "REAL", "SAFE", "JUST", "MOVE", "PLAY", "GAME", "TIME", "WELL",
    "BEST", "FAST", "FREE", "HIGH", "LONG", "SHORT", "NEXT", "PLUS", "PRIME",
    "SMART", "LIGHT", "MOON", "PEACE", "HOPE", "LOVE", "LIFE", "WORLD",
}

TICKER_HINT = re.compile(
    r"\b(token|coin|protocol|perp|perps|futures|ticker|listing|listed|airdrop|otc)\b|\$",
    re.IGNORECASE,
)


_UNIVERSE_PATH = Path(__file__).with_name("lighter_universe.json")


def register_listed(symbols: Iterable[str]) -> None:
    for symbol in symbols:
        if symbol:
            _LISTED.add(symbol.upper())


def is_ambiguous_ticker(symbol: str) -> bool:
    return (symbol or "").upper() in _AMBIGUOUS


def alias_is_english_collision(alias: str, symbol: str) -> bool:
    """True when the alias is just the ticker written as an English word."""
    a = (alias or "").strip().lower()
    s = (symbol or "").upper()
    if not a or " " in a:
        return False
    return is_ambiguous_ticker(s) and a == s.lower()


def alias_symbol(symbol: str) -> None:
    """Map a newly listed Lighter ticker so headlines like 'XAUT' resolve."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return
    _LISTED.add(sym)
    if is_ambiguous_ticker(sym):
        return
    ASSET_ALIASES.setdefault(sym.lower(), sym)


def listed_symbols() -> Set[str]:
    return set(_LISTED)


def known_symbols() -> Set[str]:
    return set(_LISTED) | set(ASSET_ALIASES.values())


def _symbols_from_universe_payload(data: dict) -> Set[str]:
    out: Set[str] = set()
    for item in data.get("symbols") or []:
        if item:
            out.add(str(item).upper())
    for book in data.get("order_books") or data.get("order_book_details") or []:
        if not isinstance(book, dict):
            continue
        status = str(book.get("status") or "active").lower()
        if status and status not in {"active", "listed", ""}:
            continue
        sym = str(book.get("symbol") or "").upper().strip()
        if sym:
            out.add(sym)
    return out


def load_catalog_snapshot(path: Optional[Path] = None) -> Set[str]:
    target = path or _UNIVERSE_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return set()
        return _symbols_from_universe_payload(data)
    except Exception:
        return set()


def save_catalog_snapshot(symbols: Iterable[str], path: Optional[Path] = None) -> None:
    """Persist symbol list without wiping live order_books catalog metadata."""
    target = path or _UNIVERSE_PATH
    now = sorted({str(item).upper() for item in symbols if item})
    payload: dict = {"symbols": now, "updated_at": time.time()}
    try:
        if target.exists():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                for key in ("order_books", "order_book_details", "code"):
                    if key in existing:
                        payload[key] = existing[key]
    except Exception:
        pass
    target.write_text(json.dumps(payload), encoding="utf-8")


def sync_catalog(symbols: Iterable[str], path: Optional[Path] = None) -> Tuple[List[str], bool]:
    """Register live Lighter symbols. Returns (new_vs_disk, first_boot)."""
    now = {str(item).upper() for item in symbols if item}
    prev = load_catalog_snapshot(path)
    first = not prev
    for symbol in now:
        alias_symbol(symbol)
    register_listed(now)
    save_catalog_snapshot(now, path)
    return sorted(now - prev), first


def bootstrap_listed_from_disk(path: Optional[Path] = None) -> int:
    """Ensure every symbol in lighter_universe.json is tradeable at import/boot."""
    symbols = load_catalog_snapshot(path)
    for symbol in symbols:
        alias_symbol(symbol)
    register_listed(symbols)
    return len(symbols)


# Load full Lighter catalog immediately so quality/entity gates see all perps.
bootstrap_listed_from_disk()
