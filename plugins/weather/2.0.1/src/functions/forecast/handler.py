"""Multiple Forecasts -- 3 upcoming temperatures at configurable intervals."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "pdk_weather_shared", str(_ROOT / "shared.py"),
)
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

resolve_location = _shared.resolve_location
fetch_timeseries = _shared.fetch_timeseries
pick_forecasts = _shared.pick_forecasts
download_icon = _shared.download_icon
fmt_temp = _shared.fmt_temp
fmt_time = _shared.fmt_time
is_wide = _shared.is_wide
weather_bg = _shared.weather_bg


# -- helpers ----------------------------------------------------------------

def _render(ctx: Any) -> None:
    """Set template state from cached forecast data."""
    ctx.state._template = "forecast"

    unit = ctx.config.get("temperature_unit", "C")
    rounding = ctx.config.get("temperature_rounding", "nearest")
    show_unit = bool(ctx.config.get("show_temperature_unit", True))
    mode = ctx.config.get("display_mode", "time")

    show_day = mode == "day"
    show_icons = mode == "icons"

    wide = is_wide(unit, rounding)
    if show_day or (show_icons and wide):
        cls = "fc-row-xs"
    elif wide or show_icons:
        cls = "fc-row-sm"
    else:
        cls = "fc-row"
    forecasts = ctx.state.get("_forecasts", [])

    if ctx.config.get("dynamic_background", True):
        first_symbol = forecasts[0]["symbol"] if forecasts else ""
        bg_top, bg_bottom = weather_bg(first_symbol)
    else:
        bg_top, bg_bottom = "#0091fe", "#02cdf9"
    ctx.state.fc_bg_top = bg_top
    ctx.state.fc_bg_bottom = bg_bottom

    ctx.state.fc_iw = "12" if show_icons else "0"
    ctx.state.fc_ih = "12" if show_icons else "0"

    for i, slot in enumerate(("fc1", "fc2", "fc3")):
        if i < len(forecasts):
            fc = forecasts[i]
            t = fmt_temp(fc["temp_c"], unit, rounding, show_unit)
            h = fmt_time(fc["iso_time"], show_day=show_day)
            ctx.state[slot] = f"{h}: {t}" if h else t

            if show_icons:
                ctx.state[f"{slot}_icon"] = download_icon(
                    fc["symbol"], ctx.storage_path,
                )
            else:
                ctx.state[f"{slot}_icon"] = ""
        else:
            ctx.state[slot] = ""
            ctx.state[f"{slot}_icon"] = ""
        ctx.state[f"{slot}_class"] = cls


# -- event handlers ---------------------------------------------------------

def on_load(ctx: Any) -> None:
    ctx.state._forecasts = []

    ctx.state._template = "forecast"
    ctx.state.fc1 = "..."
    ctx.state.fc2 = ""
    ctx.state.fc3 = ""
    ctx.state.fc1_class = "fc-row"
    ctx.state.fc2_class = "fc-row"
    ctx.state.fc3_class = "fc-row"
    ctx.state.fc1_icon = ""
    ctx.state.fc2_icon = ""
    ctx.state.fc3_icon = ""
    ctx.state.fc_iw = "0"
    ctx.state.fc_ih = "0"
    ctx.state.fc_bg_top = "#0091fe"
    ctx.state.fc_bg_bottom = "#02cdf9"


def on_poll(ctx: Any, interval: int = 60000) -> None:
    try:
        lat, lon = resolve_location(ctx.config.get("location", "Oslo"))
        ts = fetch_timeseries(lat, lon)
        interval_h = max(1, int(ctx.config.get("forecast_interval", 1)))
        skip = bool(ctx.config.get("exclude_current", False)) and interval_h < 24
        ctx.state._forecasts = pick_forecasts(
            ts, interval_hours=interval_h, skip_current=skip,
        )
    except Exception:
        pass
    _render(ctx)
