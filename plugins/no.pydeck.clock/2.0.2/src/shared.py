"""PDK Clock plugin -- displays current time and date."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


def on_load(ctx: Any) -> None:
    ctx.state.time = ""
    ctx.state.date = ""
    ctx.state.label = ""
    ctx.state.time_class = "time"
    ctx.state._template = "clock"


def on_poll(ctx: Any, interval: int = 1000) -> None:
    tz_name = ctx.config.get("timezone", "local")
    if tz_name and tz_name != "local":
        try:
            tz = ZoneInfo(tz_name)
        except (KeyError, Exception):
            tz = None
    else:
        tz = None

    now = datetime.now(tz)
    show_sec = ctx.config.get("show_seconds", False)
    hour_12 = ctx.config.get("hour_12", False)
    show_date = ctx.config.get("show_date", False)

    if hour_12:
        fmt = "%I:%M:%S" if show_sec else "%I:%M"
        ctx.state.label = now.strftime("%p")
    else:
        fmt = "%H:%M:%S" if show_sec else "%H:%M"
        ctx.state.label = ""

    ctx.state.time = now.strftime(fmt)
    ctx.state.time_class = "time-sec" if show_sec else "time"
    ctx.state.date = now.strftime("%b %d")
    ctx.state._template = "clock-date" if show_date else "clock"
