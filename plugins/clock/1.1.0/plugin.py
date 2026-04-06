"""Clock plugin for PyDeck — live digital clock (horizontal layout).

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
        for k in ("show_date", "show_seconds", "hour_12", "_device_id")
    )


def _build_display_update(config: Dict[str, Any], dt: datetime) -> Dict[str, Any]:
    """Return a display_update dict for the current time and options."""
    show_secs = bool(config.get("show_seconds", False))
    show_date = bool(config.get("show_date", False))
    hour_12 = bool(config.get("hour_12", False))

    if hour_12:
        h = dt.strftime("%I").lstrip("0") or "12"
        ampm_line = dt.strftime("%p").strip()  # e.g. "PM" — own slot
    else:
        h = dt.strftime("%H")
        ampm_line = ""

    m = dt.strftime("%M")
    s = dt.strftime("%S")
    date_str = dt.strftime("%a %d") if show_date else ""

    time_line = f"{h}:{m}"
    if show_secs:
        time_line += f":{s}"

    extras: List[str] = []
    if ampm_line:
        extras.append(ampm_line)
    if show_date:
        extras.append(date_str)

    positions = ["top", "middle", "bottom"]
    all_parts = [time_line] + extras
    if len(all_parts) == 1:
        labels = {"middle": all_parts[0]}
    else:
        # Distribute from the top down, anchoring the last item to "bottom".
        label_keys = positions[: len(all_parts) - 1] + ["bottom"]
        labels = dict(zip(label_keys, all_parts))

    # Keep text set to the time line so the core always sees a changing value
    # even though text_labels takes full rendering priority.
    return {"text": time_line, "text_labels": labels, "text_size": 0}


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
        text = update.get("text", "")

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
