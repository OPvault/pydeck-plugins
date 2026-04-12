"""Finnhub market plugin for PyDeck.

Displays a single symbol (stock, crypto, commodities like oil) and optional
change metrics for hour/day/week.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Tuple

_FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
_FINNHUB_CANDLE_URL = "https://finnhub.io/api/v1/stock/candle"
_FINNHUB_FOREX_CANDLE_URL = "https://finnhub.io/api/v1/forex/candle"
_FINNHUB_CRYPTO_CANDLE_URL = "https://finnhub.io/api/v1/crypto/candle"
_USER_AGENT = "PyDeck FinnhubPlugin-v1.1.0"
_CACHE_TTL_SECONDS = 20
_CHANGE_CACHE_TTL_SECONDS = 120

_CHANGE_PERIODS: Dict[str, Dict[str, Any]] = {
    "hour": {
        "resolution": "60",
        "lookback_seconds": 14 * 24 * 3600,
        "label": "1h",
    },
    "day": {
        "resolution": "D",
        "lookback_seconds": 120 * 24 * 3600,
        "label": "1d",
    },
    "week": {
        "resolution": "W",
        "lookback_seconds": 720 * 24 * 3600,
        "label": "1w",
    },
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

_IMPLICIT_FOREX_SYMBOLS = {
    "BCO_USD",
    "WTICO_USD",
    "XAU_USD",
}

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

_RESOLUTION_BY_PERIOD: Dict[str, str] = {
    "hour": "60",
    "day": "D",
    "week": "W",
}

# Caches avoid unnecessary API calls from poll + press actions.
_quote_cache: Dict[str, Dict[str, Any]] = {}
_change_cache: Dict[str, Dict[str, Any]] = {}
_display_signatures: Dict[str, str] = {}


def _normalize_symbol(raw: Any) -> str:
    symbol = str(raw or "AAPL").strip().upper()
    return symbol or "AAPL"


def _resolve_symbol(config: Dict[str, Any]) -> str:
    custom = str(config.get("symbol") or "").strip()
    if custom:
        alias = _SYMBOL_ALIASES.get(custom.lower())
        resolved = _normalize_symbol(alias or custom)
        if resolved in _IMPLICIT_FOREX_SYMBOLS:
            return f"OANDA:{resolved}"
        return resolved
    return "AAPL"


def _market_family(symbol: str) -> str:
    head = str(symbol or "").strip().upper().split(":", 1)[0]
    return _MARKET_FAMILY_PREFIXES.get(head, "stock")


def _normalize_change_period(raw: Any) -> str:
    period = str(raw or "day").strip().lower()
    if period in _CHANGE_PERIODS:
        return period
    return "day"


def _cache_key(config: Dict[str, Any]) -> str:
    symbol = _resolve_symbol(config)
    family = _market_family(symbol)
    decimals = int(config.get("decimals", 2) or 2)
    show_change = bool(config.get("show_change", False))
    show_currency = bool(config.get("show_currency", False))
    period = _normalize_change_period(config.get("change_period"))
    return f"{family}|{symbol}|{decimals}|{show_change}|{show_currency}|{period}"


def _get_api_key(config: Dict[str, Any]) -> str:
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("Finnhub API key is required. Configure it under Settings -> API.")
    return api_key


def _fetch_json(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError("Invalid response from Finnhub.")
    if payload.get("error"):
        raise ValueError(str(payload.get("error")))
    return payload


def _fetch_quote(symbol: str, api_key: str) -> Dict[str, Any]:
    query = urllib.parse.urlencode({"symbol": symbol, "token": api_key})
    payload = _fetch_json(f"{_FINNHUB_QUOTE_URL}?{query}")

    current = payload.get("c")
    if current is None:
        raise ValueError("No quote data returned for this symbol.")

    try:
        current = float(current)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid current price returned by Finnhub.") from exc

    quote: Dict[str, Any] = {
        "symbol": symbol,
        "price": current,
        "currency": str(payload.get("currency") or "USD").upper(),
    }

    try:
        d_raw = payload.get("d")
        dp_raw = payload.get("dp")
        if d_raw is not None:
            quote["change"] = float(d_raw)
        if dp_raw is not None:
            quote["percent_change"] = float(dp_raw)
    except (TypeError, ValueError):
        pass

    return quote


def _fetch_candle_series(symbol: str, api_key: str, family: str, resolution: str, from_ts: int, to_ts: int) -> Dict[str, Any]:
    if family == "crypto":
        base_url = _FINNHUB_CRYPTO_CANDLE_URL
    elif family == "forex":
        base_url = _FINNHUB_FOREX_CANDLE_URL
    else:
        base_url = _FINNHUB_CANDLE_URL

    query = urllib.parse.urlencode({
        "symbol": symbol,
        "resolution": resolution,
        "from": from_ts,
        "to": to_ts,
        "token": api_key,
    })
    return _fetch_json(f"{base_url}?{query}")


def _series_from_payload(payload: Dict[str, Any]) -> list[float]:
    closes = payload.get("c")
    if not isinstance(closes, list) or len(closes) < 2:
        raise ValueError("Not enough candle data to calculate change.")
    try:
        return [float(v) for v in closes]
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid candle data returned by Finnhub.") from exc


def _fetch_period_change(symbol: str, period: str, api_key: str, family: str) -> Tuple[float, float]:
    cfg = _CHANGE_PERIODS[period]
    to_ts = int(time.time())
    from_ts = max(0, to_ts - int(cfg["lookback_seconds"]))

    payload = _fetch_candle_series(symbol, api_key, family, cfg["resolution"], from_ts, to_ts)
    if payload.get("s") != "ok":
        raise ValueError("No candle data available for selected period.")

    closes = _series_from_payload(payload)
    prev = closes[-2]
    latest = closes[-1]
    if prev == 0:
        raise ValueError("Cannot calculate percentage change from zero baseline.")

    change = latest - prev
    percent_change = (change / prev) * 100.0
    return change, percent_change


def _fetch_latest_close(symbol: str, api_key: str, family: str) -> Dict[str, Any]:
    attempts = (
        ("60", 14 * 24 * 3600),
        ("D", 120 * 24 * 3600),
        ("W", 720 * 24 * 3600),
    )

    last_error: ValueError | None = None
    now = int(time.time())
    for resolution, lookback_seconds in attempts:
        try:
            payload = _fetch_candle_series(
                symbol,
                api_key,
                family,
                resolution,
                max(0, now - lookback_seconds),
                now,
            )
            if payload.get("s") != "ok":
                continue

            closes = _series_from_payload(payload)
            return {
                "symbol": symbol,
                "price": closes[-1],
                "currency": "USD",
            }
        except ValueError as exc:
            last_error = exc

    raise ValueError("No price data available for this symbol.") from last_error


def _get_quote(config: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    symbol = _resolve_symbol(config)
    family = _market_family(symbol)
    api_key = _get_api_key(config)

    now = time.time()
    cached = _quote_cache.get(f"{family}|{symbol}")
    if not force and cached and (now - float(cached.get("fetched_at", 0.0))) < _CACHE_TTL_SECONDS:
        data = cached.get("quote")
        if isinstance(data, dict):
            return data

    if family == "stock":
        quote = _fetch_quote(symbol, api_key)
    else:
        # For crypto/forex-like symbols, quote() is not reliable. Use candle
        # data and fall back to wider resolutions when intraday data is sparse.
        quote = _fetch_latest_close(symbol, api_key, family)

    _quote_cache[f"{family}|{symbol}"] = {
        "fetched_at": now,
        "quote": quote,
    }
    return quote


def _get_change(config: Dict[str, Any], quote: Dict[str, Any], force: bool = False) -> Tuple[float, float, str]:
    symbol = _resolve_symbol(config)
    family = _market_family(symbol)
    period = _normalize_change_period(config.get("change_period"))
    label = str(_CHANGE_PERIODS[period]["label"])

    # Prefer quote endpoint values for day change when available.
    if family == "stock" and period == "day":
        change = quote.get("change")
        percent_change = quote.get("percent_change")
        if isinstance(change, (int, float)) and isinstance(percent_change, (int, float)):
            return float(change), float(percent_change), label

    cache_key = f"{family}|{symbol}|{period}"
    now = time.time()
    cached = _change_cache.get(cache_key)
    if not force and cached and (now - float(cached.get("fetched_at", 0.0))) < _CHANGE_CACHE_TTL_SECONDS:
        cached_value = cached.get("value")
        if isinstance(cached_value, tuple) and len(cached_value) == 2:
            if isinstance(cached_value[0], (int, float)) and isinstance(cached_value[1], (int, float)):
                return float(cached_value[0]), float(cached_value[1]), label

    api_key = _get_api_key(config)
    change_tuple = _fetch_period_change(symbol, period, api_key, family)
    _change_cache[cache_key] = {
        "fetched_at": now,
        "value": change_tuple,
    }
    return float(change_tuple[0]), float(change_tuple[1]), label


def _format_price(price: float, decimals: int) -> str:
    safe_decimals = max(0, min(8, int(decimals)))
    return f"{price:.{safe_decimals}f}"


def _format_change(change: float, percent_change: float) -> str:
    sign = "+" if change > 0 else ""
    return f"{sign}{change:.2f} ({sign}{percent_change:.2f}%)"


def _build_display_update(config: Dict[str, Any], quote: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    symbol = str(quote.get("symbol") or _resolve_symbol(config))
    price = float(quote["price"])
    decimals = int(config.get("decimals", 2) or 2)

    price_text = _format_price(price, decimals)
    if bool(config.get("show_currency", False)):
        currency = str(quote.get("currency") or "USD")
        price_text = f"{price_text} {currency}"

    labels = {
        "top": symbol,
        "bottom": price_text,
    }

    display_update: Dict[str, Any] = {
        "text_labels": labels,
        "text": "",
        "text_label_sizes": {
            "top": 14,
            "bottom": 16,
        },
    }

    if bool(config.get("show_change", False)):
        try:
            change, percent_change, period_label = _get_change(config, quote, force=False)
            labels["middle"] = f"{period_label} {_format_change(change, percent_change)}"
            display_update["text_label_sizes"]["middle"] = 11
        except ValueError:
            pass

    signature = "|".join([
        str(labels.get("top", "")),
        str(labels.get("middle", "")),
        str(labels.get("bottom", "")),
    ])
    return display_update, signature


def _build_result_payload(config: Dict[str, Any], quote: Dict[str, Any], display_update: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "success": True,
        "symbol": quote.get("symbol"),
        "price": quote.get("price"),
        "change": quote.get("change"),
        "percent_change": quote.get("percent_change"),
        "display_update": display_update,
    }

    if bool(config.get("show_change", False)):
        try:
            change, percent_change, period_label = _get_change(config, quote, force=False)
            payload["selected_change_period"] = period_label
            payload["selected_change"] = change
            payload["selected_percent_change"] = percent_change
        except ValueError:
            pass

    return payload


def show_stock_price(config: Dict[str, Any]) -> Dict[str, Any]:
    """Manual press: fetch and show the configured symbol price."""
    try:
        quote = _get_quote(config, force=True)
        display_update, signature = _build_display_update(config, quote)
        _display_signatures[_cache_key(config)] = signature
        return _build_result_payload(config, quote, display_update)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except urllib.error.HTTPError as exc:
        return {
            "success": False,
            "error": f"Finnhub API HTTP {exc.code}: {exc.reason}",
        }
    except urllib.error.URLError as exc:
        return {"success": False, "error": f"Network error: {exc.reason}"}


def poll_stock_price(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll: update display only when output changes."""
    try:
        quote = _get_quote(config, force=False)
        display_update, signature = _build_display_update(config, quote)
        key = _cache_key(config)

        if _display_signatures.get(key) == signature:
            return {}

        _display_signatures[key] = signature
        return {"display_update": display_update}
    except (ValueError, urllib.error.HTTPError, urllib.error.URLError, OSError):
        return {}
