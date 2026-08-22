"""Market Price -- one Finnhub symbol on the button face.

Poll refreshes from cache; a press forces a fresh request.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict

# src/shared.py is loaded by path under a plugin-specific module name rather
# than with a bare ``import shared``.  Every PDK plugin's shared module is
# called "shared", so a plain import resolves to whichever plugin got there
# first and this module silently fails to load -- taking the button's whole
# state with it.
_SHARED_NAME = "pdk_finnhub_shared"
_SHARED_PATH = Path(__file__).resolve().parent.parent.parent / "shared.py"


def _load_shared() -> Any:
    cached = sys.modules.get(_SHARED_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_SHARED_NAME, str(_SHARED_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[_SHARED_NAME] = module
    spec.loader.exec_module(module)
    return module


shared = _load_shared()
FinnhubError = shared.FinnhubError

# The PDK runtime keeps ONE state dict per function, shared by every button
# using it, so the last good face has to be remembered per button here rather
# than read back off ctx.state -- otherwise a button whose refresh failed would
# redraw whichever symbol was polled last.
_last_face: Dict[str, Dict[str, str]] = {}

_BLANK_FACE: Dict[str, str] = {
    "_template": "quote",
    "symbol": "",
    "symbol_size": "sz-13",
    "price": "--",
    "price_size": "sz-24",
    "period": "",
    "change": "",
    "change_class": "chg-flat",
    "change_size": "sz-11",
    "error": "",
    "error_size": "sz-11",
}


def on_load(ctx: Any) -> None:
    _apply(ctx, _BLANK_FACE)


def on_press(ctx: Any) -> None:
    """Refresh now, bypassing the quote cache."""
    _refresh(ctx, force=True)


def on_poll(ctx: Any, interval: int = 15000) -> None:
    _refresh(ctx, force=False)


# ── internals ──────────────────────────────────────────────────────────────────


def _apply(ctx: Any, face: Dict[str, str]) -> None:
    for key, value in face.items():
        ctx.state[key] = value


def _button_key(ctx: Any, symbol: str) -> str:
    button_id = (getattr(ctx, "config", None) or {}).get("_button_id", "?")
    return f"{button_id}|{symbol}"


def _refresh(ctx: Any, *, force: bool) -> None:
    config = getattr(ctx, "config", None) or {}
    symbol = shared.resolve_symbol(config)
    label = shared.display_symbol(symbol)

    try:
        api_key = shared.load_api_key(ctx)
        quote = shared.get_quote(symbol, api_key, force=force)
    except FinnhubError as exc:
        _fail(ctx, symbol, label, exc)
        return

    price = shared.format_price(float(quote["price"]), config.get("decimals", 2))
    if config.get("show_currency", False):
        price = f"{price} {quote.get('currency') or 'USD'}"

    face = dict(_BLANK_FACE)
    face["symbol"] = label
    face["symbol_size"] = shared.fit_size(label, shared.SYMBOL_MAX, min_size=8)
    face["price"] = price
    face["price_size"] = shared.fit_size(price, shared.PRICE_MAX)

    if config.get("show_change", False):
        period = shared.normalize_change_period(config.get("change_period"))
        try:
            _, percent = shared.get_change(symbol, period, api_key, quote, force=force)
        except FinnhubError as exc:
            # The price is good and only the change series failed, so drop the
            # change line rather than the whole face.
            print(f"[finnhub] {symbol} {period} change unavailable: {exc}")
        else:
            label_text = shared.period_label(period)
            change = shared.format_percent(percent)
            face["_template"] = "quote-change"
            face["period"] = label_text
            face["change"] = change
            face["change_class"] = shared.change_class(percent)
            face["change_size"] = shared.fit_size(
                change,
                shared.CHANGE_MAX,
                budget=shared.change_budget(label_text),
            )

    _last_face[_button_key(ctx, symbol)] = face
    _apply(ctx, face)


def _fail(ctx: Any, symbol: str, label: str, exc: FinnhubError) -> None:
    """Keep the last good face when there is one; otherwise say what broke."""
    print(f"[finnhub] {symbol}: {exc}")

    previous = _last_face.get(_button_key(ctx, symbol))
    if previous is not None:
        _apply(ctx, previous)
        return

    face = dict(_BLANK_FACE)
    face["_template"] = "quote-error"
    face["symbol"] = label
    face["symbol_size"] = shared.fit_size(label, shared.SYMBOL_MAX, min_size=8)
    face["error"] = exc.short
    face["error_size"] = shared.fit_size(exc.short, shared.ERROR_MAX)
    _apply(ctx, face)
