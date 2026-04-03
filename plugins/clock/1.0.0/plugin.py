"""Clock plugin for PyDeck — digital clock with Horizontal and Vertical styles.

Horizontal 12-hour mode shows ``AM``/``PM`` on its own line under the time.

Pressing the button forces an immediate refresh. The background poller
(poll_clock) updates the button every second.

The core applies ``preload_display_updates`` on UNIX second boundaries so the
next several faces are known ahead of time — avoiding 1–2s gaps from coarse
poll timing plus disk/JSON work.
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Any, Dict, List

# ── Change-detection state ─────────────────────────────────────────────────────

_last_text: Dict[str, str] = {}

# How many upcoming second-boundary frames to register with the core scheduler.
_NUM_PRELOAD_SECONDS = 5


def _config_key(config: Dict[str, Any]) -> str:
    return ":".join(
        str(config.get(k, ""))
        for k in (
            "clock_style",
            "show_date",
            "show_seconds",
            "hour_12",
            "_device_id",
        )
    )


def _build_display_update(config: Dict[str, Any], dt: datetime) -> Dict[str, Any]:
    """Return a display_update dict for the current style, time, and options."""
    style = str(config.get("clock_style") or "horizontal")
    show_secs = bool(config.get("show_seconds", False))
    show_date = bool(config.get("show_date", False))
    hour_12 = bool(config.get("hour_12", False))

    if hour_12:
        h = dt.strftime("%I").lstrip("0") or "12"
        ampm_suffix = dt.strftime(" %p")  # vertical: append to block
        ampm_line = dt.strftime("%p").strip()  # horizontal: own line (AM / PM)
    else:
        h = dt.strftime("%H")
        ampm_suffix = ""
        ampm_line = ""

    m = dt.strftime("%M")
    s = dt.strftime("%S")
    date_str = dt.strftime("%a %d") if show_date else ""

    if style == "vertical":
        parts = [h, m]
        if show_secs:
            parts.append(s)
        if show_date:
            parts.append(date_str)
        text = "\n".join(parts)
        if ampm_suffix:
            text += ampm_suffix

        row_count = len(parts)
        text_size = {1: 36, 2: 30, 3: 24, 4: 18}.get(row_count, 18)

        return {"text": text, "text_size": text_size}

    # Horizontal — time on first line; 12h puts AM/PM on second line; date below that.
    time_line = f"{h}:{m}"
    if show_secs:
        time_line += f":{s}"
    lines = [time_line]
    if ampm_line:
        lines.append(ampm_line)
    if show_date:
        lines.append(date_str)
    return {"text": "\n".join(lines), "text_size": 0}


def _build_preload_entries(
    config: Dict[str, Any], from_unix_sec: int, count: int
) -> List[Dict[str, Any]]:
    """Schedule display_update dicts at upcoming integer UNIX second timestamps."""
    out: List[Dict[str, Any]] = []
    for i in range(1, count + 1):
        ts = float(from_unix_sec + i)
        dt = datetime.fromtimestamp(ts)
        out.append(
            {
                "apply_at": ts,
                "display_update": _build_display_update(config, dt),
            }
        )
    return out


def show_clock(config: Dict[str, Any]) -> Dict[str, Any]:
    """Manual press — immediately refresh the button with the current time."""
    try:
        now_ts = time.time()
        cur_sec = math.floor(now_ts)
        dt = datetime.fromtimestamp(cur_sec)
        update = _build_display_update(config, dt)
        _last_text.pop(_config_key(config), None)
        preloads = _build_preload_entries(config, cur_sec, _NUM_PRELOAD_SECONDS)
        return {
            "success": True,
            "display_update": update,
            "preload_display_updates": preloads,
        }
    except Exception as exc:
        return {"success": False, "error": f"Clock error: {exc}"}


def poll_clock(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll — update when the displayed second changes; preload next frames."""
    try:
        now_ts = time.time()
        cur_sec = math.floor(now_ts)
        dt = datetime.fromtimestamp(cur_sec)
        key = _config_key(config)
        update = _build_display_update(config, dt)
        text = update["text"]

        if _last_text.get(key) == text:
            return {}

        _last_text[key] = text
        preloads = _build_preload_entries(config, cur_sec, _NUM_PRELOAD_SECONDS)
        return {
            "display_update": update,
            "preload_display_updates": preloads,
        }
    except Exception:
        return {}
