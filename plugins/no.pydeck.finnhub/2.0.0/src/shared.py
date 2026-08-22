"""Finnhub PDK plugin — market data helpers shared by the function handlers.

Wraps the Finnhub REST API: ``/quote`` for equities, candle series for the
crypto and forex-style feeds where ``/quote`` is unreliable, short-lived
caches so a press and the poll loop do not each burn a request, and the
formatting helpers the templates need to fit a value onto a 72px button.

Per-function handlers live under ``src/functions/<name>/handler.py``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

_QUOTE_URL = "https://finnhub.io/api/v1/quote"
_STOCK_CANDLE_URL = "https://finnhub.io/api/v1/stock/candle"
_FOREX_CANDLE_URL = "https://finnhub.io/api/v1/forex/candle"
_CRYPTO_CANDLE_URL = "https://finnhub.io/api/v1/crypto/candle"

_USER_AGENT = "PyDeck FinnhubPlugin-v2.0.0"
_TIMEOUT = 10

_QUOTE_TTL = 20.0
_CHANGE_TTL = 120.0

PLUGIN_ID = "no.pydeck.finnhub"
# The core writes credentials under the RDNN id but resolves every alias, so a
# plugin reading the file itself has to try both -- RDNN last so a migrated
# blob wins over the pre-PDK "finnhub" entry.
_LEGACY_PLUGIN_IDS = ("finnhub",)
_CREDS_PATH = Path.home() / ".config" / "pydeck" / "core" / "credentials.json"

DEFAULT_SYMBOL = "AAPL"

_CHANGE_PERIODS: Dict[str, Dict[str, Any]] = {
    "hour": {"resolution": "60", "lookback_seconds": 14 * 24 * 3600, "label": "1h"},
    "day": {"resolution": "D", "lookback_seconds": 120 * 24 * 3600, "label": "1d"},
    "week": {"resolution": "W", "lookback_seconds": 720 * 24 * 3600, "label": "1w"},
}

_SYMBOL_ALIASES: Dict[str, str] = {
    "btc": "BINANCE:BTCUSDT",
    "bitcoin": "BINANCE:BTCUSDT",
    "eth": "BINANCE:ETHUSDT",
    "ethereum": "BINANCE:ETHUSDT",
    "brent": "OANDA:BCO_USD",
    "oil": "OANDA:BCO_USD",
    "crude": "OANDA:BCO_USD",
    "wti": "OANDA:WTICO_USD",
    "wti oil": "OANDA:WTICO_USD",
    "wtico_usd": "OANDA:WTICO_USD",
    "xau": "OANDA:XAU_USD",
    "gold": "OANDA:XAU_USD",
}

# Bare symbols that only resolve on the forex feed, typed without a prefix.
_IMPLICIT_FOREX_SYMBOLS = {"BCO_USD", "WTICO_USD", "XAU_USD"}

_MARKET_FAMILY_PREFIXES: Dict[str, str] = {
    "BINANCE": "crypto",
    "COINBASE": "crypto",
    "KRAKEN": "crypto",
    "BITSTAMP": "crypto",
    "BITFINEX": "crypto",
    "OANDA": "forex",
    "FXCM": "forex",
    "FOREX.COM": "forex",
    "IC MARKETS": "forex",
    "FXPRO": "forex",
}

# A resolved symbol is too wide for the button face, so the aliases get their
# common ticker back for display.
_DISPLAY_NAMES: Dict[str, str] = {
    "BINANCE:BTCUSDT": "BTC",
    "BINANCE:ETHUSDT": "ETH",
    "OANDA:BCO_USD": "BRENT",
    "OANDA:WTICO_USD": "WTI",
    "OANDA:XAU_USD": "GOLD",
}

# Caches keyed by symbol, shared by every button showing it.
_quote_cache: Dict[str, Dict[str, Any]] = {}
_change_cache: Dict[str, Dict[str, Any]] = {}


class FinnhubError(Exception):
    """A failure worth putting on the button face.

    ``short`` is the version that fits there; ``str(exc)`` stays readable for
    the backend console.
    """

    def __init__(self, message: str, short: str = "Error") -> None:
        super().__init__(message)
        self.short = short


# ── Credentials ────────────────────────────────────────────────────────────────


def load_api_key(ctx: Any) -> str:
    """Return the configured Finnhub API key.

    ``ctx.credentials`` is populated on press and on the server's poll, but the
    hardware listener dispatches poll without it -- so read credentials.json
    directly and treat ctx as an overlay when present.
    """
    merged: Dict[str, Any] = {}
    try:
        if _CREDS_PATH.is_file():
            raw = json.loads(_CREDS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in (*_LEGACY_PLUGIN_IDS, PLUGIN_ID):
                    entry = raw.get(key)
                    if isinstance(entry, dict):
                        merged.update({k: v for k, v in entry.items() if v})
    except (OSError, ValueError):
        pass

    for source in (getattr(ctx, "credentials", None), getattr(ctx, "config", None)):
        if isinstance(source, dict):
            merged.update({k: v for k, v in source.items() if k == "api_key" and v})

    api_key = str(merged.get("api_key") or "").strip()
    if not api_key:
        raise FinnhubError(
            "Finnhub API key is required. Add it under Settings -> Credentials.",
            "No API key",
        )
    return api_key


# ── Symbols ────────────────────────────────────────────────────────────────────


def resolve_symbol(config: Dict[str, Any]) -> str:
    """Map whatever the user typed onto a symbol Finnhub understands."""
    raw = str(config.get("symbol") or "").strip()
    if not raw:
        return DEFAULT_SYMBOL

    alias = _SYMBOL_ALIASES.get(raw.lower())
    resolved = (alias or raw).strip().upper() or DEFAULT_SYMBOL
    if resolved in _IMPLICIT_FOREX_SYMBOLS:
        return f"OANDA:{resolved}"
    return resolved


def market_family(symbol: str) -> str:
    """``stock``, ``crypto``, or ``forex`` -- picks the endpoint to query."""
    head = str(symbol or "").strip().upper().split(":", 1)[0]
    return _MARKET_FAMILY_PREFIXES.get(head, "stock")


def display_symbol(symbol: str) -> str:
    """The short ticker to draw, e.g. ``BINANCE:BTCUSDT`` -> ``BTC``."""
    known = _DISPLAY_NAMES.get(symbol)
    if known:
        return known
    return symbol.split(":", 1)[-1] if ":" in symbol else symbol


def normalize_change_period(raw: Any) -> str:
    period = str(raw or "day").strip().lower()
    return period if period in _CHANGE_PERIODS else "day"


def period_label(period: str) -> str:
    return str(_CHANGE_PERIODS[normalize_change_period(period)]["label"])


# ── HTTP ───────────────────────────────────────────────────────────────────────


def _fetch_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise FinnhubError(
            f"Finnhub API HTTP {exc.code}: {exc.reason}",
            _http_short(exc.code),
        ) from exc
    except urllib.error.URLError as exc:
        raise FinnhubError(f"Network error: {exc.reason}", "Offline") from exc
    except (OSError, ValueError) as exc:
        raise FinnhubError(f"Bad response from Finnhub: {exc}", "Bad data") from exc

    if not isinstance(payload, dict):
        raise FinnhubError("Invalid response from Finnhub.", "Bad data")
    if payload.get("error"):
        raise FinnhubError(str(payload.get("error")), "API error")
    return payload


def _http_short(code: int) -> str:
    if code in (401, 403):
        return "Bad API key"
    if code == 429:
        return "Rate limit"
    return f"HTTP {code}"


def _fetch_quote(symbol: str, api_key: str) -> Dict[str, Any]:
    query = urllib.parse.urlencode({"symbol": symbol, "token": api_key})
    payload = _fetch_json(f"{_QUOTE_URL}?{query}")

    current = payload.get("c")
    if current is None:
        raise FinnhubError("No quote data returned for this symbol.", "No data")
    try:
        price = float(current)
    except (TypeError, ValueError) as exc:
        raise FinnhubError("Invalid current price returned by Finnhub.", "Bad data") from exc

    quote: Dict[str, Any] = {
        "symbol": symbol,
        "price": price,
        "currency": str(payload.get("currency") or "USD").upper(),
    }

    # d/dp are the day's absolute and percent change; absent outside market
    # hours on some feeds, so they stay optional.
    try:
        if payload.get("d") is not None:
            quote["change"] = float(payload["d"])
        if payload.get("dp") is not None:
            quote["percent_change"] = float(payload["dp"])
    except (TypeError, ValueError):
        pass

    return quote


def _fetch_candles(
    symbol: str,
    api_key: str,
    family: str,
    resolution: str,
    from_ts: int,
    to_ts: int,
) -> Dict[str, Any]:
    if family == "crypto":
        base_url = _CRYPTO_CANDLE_URL
    elif family == "forex":
        base_url = _FOREX_CANDLE_URL
    else:
        base_url = _STOCK_CANDLE_URL

    query = urllib.parse.urlencode({
        "symbol": symbol,
        "resolution": resolution,
        "from": from_ts,
        "to": to_ts,
        "token": api_key,
    })
    return _fetch_json(f"{base_url}?{query}")


def _closes(payload: Dict[str, Any]) -> List[float]:
    closes = payload.get("c")
    if not isinstance(closes, list) or len(closes) < 2:
        raise FinnhubError("Not enough candle data to calculate change.", "No data")
    try:
        return [float(v) for v in closes]
    except (TypeError, ValueError) as exc:
        raise FinnhubError("Invalid candle data returned by Finnhub.", "Bad data") from exc


def _fetch_latest_close(symbol: str, api_key: str, family: str) -> Dict[str, Any]:
    """Last close for a crypto/forex symbol, widening the resolution as needed."""
    attempts = (
        ("60", 14 * 24 * 3600),
        ("D", 120 * 24 * 3600),
        ("W", 720 * 24 * 3600),
    )

    now = int(time.time())
    last_error: FinnhubError | None = None
    for resolution, lookback in attempts:
        try:
            payload = _fetch_candles(
                symbol, api_key, family, resolution, max(0, now - lookback), now,
            )
            if payload.get("s") != "ok":
                continue
            return {
                "symbol": symbol,
                "price": _closes(payload)[-1],
                "currency": "USD",
            }
        except FinnhubError as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    raise FinnhubError("No price data available for this symbol.", "No data")


# ── Cached lookups ─────────────────────────────────────────────────────────────


def get_quote(symbol: str, api_key: str, *, force: bool = False) -> Dict[str, Any]:
    """Current price for *symbol*, served from cache unless *force*."""
    family = market_family(symbol)
    key = f"{family}|{symbol}"
    now = time.time()

    cached = _quote_cache.get(key)
    if not force and cached and (now - float(cached["fetched_at"])) < _QUOTE_TTL:
        return dict(cached["quote"])

    if family == "stock":
        quote = _fetch_quote(symbol, api_key)
    else:
        # /quote is not reliable for these feeds -- read the candle series and
        # fall back to wider resolutions when intraday data is sparse.
        quote = _fetch_latest_close(symbol, api_key, family)

    _quote_cache[key] = {"fetched_at": now, "quote": quote}
    return dict(quote)


def get_change(
    symbol: str,
    period: str,
    api_key: str,
    quote: Dict[str, Any],
    *,
    force: bool = False,
) -> Tuple[float, float]:
    """``(absolute, percent)`` change over *period* for *symbol*."""
    family = market_family(symbol)
    period = normalize_change_period(period)

    # The quote endpoint already carries the day change for equities.
    if family == "stock" and period == "day":
        change = quote.get("change")
        percent = quote.get("percent_change")
        if isinstance(change, (int, float)) and isinstance(percent, (int, float)):
            return float(change), float(percent)

    key = f"{family}|{symbol}|{period}"
    now = time.time()
    cached = _change_cache.get(key)
    if not force and cached and (now - float(cached["fetched_at"])) < _CHANGE_TTL:
        return cached["value"]

    cfg = _CHANGE_PERIODS[period]
    to_ts = int(time.time())
    from_ts = max(0, to_ts - int(cfg["lookback_seconds"]))
    payload = _fetch_candles(symbol, api_key, family, str(cfg["resolution"]), from_ts, to_ts)
    if payload.get("s") != "ok":
        raise FinnhubError("No candle data available for selected period.", "No data")

    closes = _closes(payload)
    previous, latest = closes[-2], closes[-1]
    if previous == 0:
        raise FinnhubError("Cannot calculate change from a zero baseline.", "No data")

    value = (latest - previous, ((latest - previous) / previous) * 100.0)
    _change_cache[key] = {"fetched_at": now, "value": value}
    return value


# ── Formatting ─────────────────────────────────────────────────────────────────


def format_price(price: float, decimals: Any) -> str:
    try:
        places = int(decimals)
    except (TypeError, ValueError):
        places = 2
    return f"{price:.{max(0, min(8, places))}f}"


def format_percent(percent: float) -> str:
    sign = "+" if percent > 0 else ""
    return f"{sign}{percent:.2f}%"


def change_class(percent: float) -> str:
    if percent > 0:
        return "chg-up"
    if percent < 0:
        return "chg-down"
    return "chg-flat"


# ── Fitting text to the button ─────────────────────────────────────────────────
#
# <text> is single-line and the renderer neither wraps it nor shrinks it, so a
# long price is simply cut off at the edge of the button.  Every line on the
# face therefore carries a size class picked here: estimate the string's width
# in em, then take the largest size that still fits.
#
# Advance widths are measured from DejaVu Sans Bold, the renderer's default
# face, rounded up so a wide glyph run errs towards the smaller size.

_ADVANCE_EM = {
    " ": 0.35,
    ".": 0.38,
    ",": 0.38,
    ":": 0.40,
    "-": 0.42,
    "/": 0.37,
    "+": 0.84,
    "%": 1.01,
}
_DIGIT_EM = 0.70
_UPPER_EM = 0.80
_OTHER_EM = 0.66

# The 72px base canvas less the .face padding, minus a pixel of slack.  Sizes
# resolve against the canvas, so this scales with the device.
USABLE_PX = 63.0

# Every size the stylesheet defines a .sz-<n> rule for, largest first.
_SIZES = (24, 21, 18, 16, 14, 13, 12, 11, 10, 9, 8, 7)


def text_em(text: str) -> float:
    """Width of *text* in em, under the renderer's default bold face."""
    total = 0.0
    for char in text:
        known = _ADVANCE_EM.get(char)
        if known is not None:
            total += known
        elif char.isdigit():
            total += _DIGIT_EM
        elif char.isupper():
            total += _UPPER_EM
        else:
            total += _OTHER_EM
    return total


def fit_size(
    text: str,
    max_size: int,
    min_size: int = 7,
    budget: float = USABLE_PX,
) -> str:
    """The largest ``sz-<n>`` class in which *text* fits *budget* pixels."""
    em = text_em(text)
    for size in _SIZES:
        if size > max_size:
            continue
        if size < min_size:
            break
        if em <= 0 or em * size <= budget:
            return f"sz-{size}"
    return f"sz-{min_size}"


# Sizes the face uses, and the width the period label plus its gap costs the
# change line.
SYMBOL_MAX = 13
PRICE_MAX = 24
CHANGE_MAX = 11
ERROR_MAX = 11
PERIOD_SIZE = 8
CHANGE_ROW_GAP = 3


def change_budget(period: str) -> float:
    """Pixels left on the change row once the period label has its share."""
    return USABLE_PX - text_em(period) * PERIOD_SIZE - CHANGE_ROW_GAP
