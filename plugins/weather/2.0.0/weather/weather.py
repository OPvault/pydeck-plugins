"""Current Weather -- shows temp + icon, tap for today's high/low."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "pdk_weather_shared", str(_ROOT / "plugin.py"),
)
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

resolve_location = _shared.resolve_location
fetch_timeseries = _shared.fetch_timeseries
current_conditions = _shared.current_conditions
download_icon = _shared.download_icon
fmt_temp = _shared.fmt_temp
is_wide = _shared.is_wide
weather_bg = _shared.weather_bg


# -- helpers ----------------------------------------------------------------

def _cfg(ctx: Any) -> tuple:
    """Unpack the three temperature-formatting config values."""
    unit = ctx.config.get("temperature_unit", "C")
    rounding = ctx.config.get("temperature_rounding", "nearest")
    show_unit = bool(ctx.config.get("show_temperature_unit", True))
    return unit, rounding, show_unit


def _render(ctx: Any) -> None:
    """Set template state from cached weather data."""
    unit, rounding, show_unit = _cfg(ctx)
    small = is_wide(unit, rounding)
    view = ctx.state.get("view", "main")

    if ctx.config.get("dynamic_background", True):
        bg_top, bg_bottom = weather_bg(ctx.state.get("_symbol", ""))
    else:
        bg_top, bg_bottom = "#0091fe", "#02cdf9"
    ctx.state.bg_top = bg_top
    ctx.state.bg_bottom = bg_bottom

    if view == "detail":
        ctx.state._template = "weather-detail"
        sm = "-sm" if small else ""
        ctx.state.arrow_hi = "\u25b2"
        ctx.state.arrow_lo = "\u25bc"
        ctx.state.val_hi = fmt_temp(ctx.state._high, unit, rounding, show_unit)
        ctx.state.val_lo = fmt_temp(ctx.state._low, unit, rounding, show_unit)
        ctx.state.val_hi_class = f"val-hi{sm}"
        ctx.state.val_lo_class = f"val-lo{sm}"
    else:
        ctx.state._template = "weather"
        ctx.state.temp_class = "temp-sm" if small else "temp"
        ctx.state.line1 = fmt_temp(ctx.state._temp, unit, rounding, show_unit)
        ctx.state.line2 = datetime.now().strftime("%a").upper()
        ctx.state.icon_src = ctx.state._icon
        ctx.state.icon_w = "24"
        ctx.state.icon_h = "24"


# -- event handlers ---------------------------------------------------------

def on_load(ctx: Any) -> None:
    ctx.state._temp = 0.0
    ctx.state._high = 0.0
    ctx.state._low = 0.0
    ctx.state._icon = ""
    ctx.state._symbol = ""
    ctx.state.view = "main"

    ctx.state._template = "weather"
    ctx.state.line1 = "..."
    ctx.state.line2 = ""
    ctx.state.icon_src = ""
    ctx.state.icon_w = "0"
    ctx.state.icon_h = "0"
    ctx.state.temp_class = "temp"
    ctx.state.val_hi_class = "val-hi"
    ctx.state.val_lo_class = "val-lo"


def on_press(ctx: Any) -> None:
    ctx.state.view = "detail" if ctx.state.get("view") == "main" else "main"
    _render(ctx)


def on_poll(ctx: Any, interval: int = 60000) -> None:
    try:
        lat, lon = resolve_location(ctx.config.get("location", "Oslo"))
        ts = fetch_timeseries(lat, lon)
        temp, high, low, symbol = current_conditions(ts)
        ctx.state._temp = temp
        ctx.state._high = high
        ctx.state._low = low
        ctx.state._symbol = symbol
        ctx.state._icon = download_icon(symbol, ctx.storage_path)
    except Exception:
        pass
    _render(ctx)
