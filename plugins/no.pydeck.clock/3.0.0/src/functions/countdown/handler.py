"""Countdown -- a per-button timer.  Press to start, press again to pause.

Timer state lives in a JSON file under the plugin's storage directory rather
than in ``ctx.state``, for two reasons: PDK state is per *function*, not per
button, and the server and the device listener are separate processes with
separate runtimes.  The file is the one place both can agree on.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("pdk_clock_shared", str(_ROOT / "shared.py"))
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

_TIMERS_FILE = "timers.json"
_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([hms])", re.IGNORECASE)

# (mtime, parsed) so a 1 Hz poll across several timer buttons re-reads the file
# only when a press has actually rewritten it.
_cache: Tuple[float, Dict[str, Any]] = (-1.0, {})


def parse_duration(raw: Any) -> float:
    """Seconds from ``"90"``, ``"5:00"``, ``"1:30:00"``, ``"25m"`` or ``"1h30m"``."""
    text = str(raw or "").strip().lower()
    if not text:
        return 0.0

    if ":" in text:
        total = 0.0
        for part in text.split(":"):
            try:
                total = total * 60.0 + float(part or 0)
            except ValueError:
                return 0.0
        return total

    units = _DURATION_RE.findall(text)
    if units:
        scale = {"h": 3600.0, "m": 60.0, "s": 1.0}
        return sum(float(value) * scale[unit.lower()] for value, unit in units)

    try:
        return float(text)
    except ValueError:
        return 0.0


def _path(ctx: Any) -> Path:
    return Path(ctx.storage_path) / _TIMERS_FILE


def _load(ctx: Any) -> Dict[str, Any]:
    global _cache
    path = _path(ctx)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _cache[0] == mtime:
        return _cache[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        data = {}
    _cache = (mtime, data)
    return data


def _save(ctx: Any, timers: Dict[str, Any]) -> None:
    global _cache
    path = _path(ctx)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(timers), encoding="utf-8")
        _cache = (path.stat().st_mtime, timers)
    except OSError:
        pass


def _key(ctx: Any) -> str:
    button_id = ctx.config.get("_button_id")
    return str(button_id) if button_id is not None else "default"


def _remaining(timer: Optional[Dict[str, Any]], total: float) -> Tuple[float, bool]:
    """Return ``(seconds_left, running)`` for a stored timer entry."""
    if not timer:
        return total, False
    if timer.get("state") == "running":
        return float(timer.get("ends_at", 0.0)) - time.time(), True
    return float(timer.get("remaining", total)), False


def render(ctx: Any) -> None:
    cfg = ctx.config
    total = parse_duration(cfg.get("duration", "5:00")) or 300.0
    timer = _load(ctx).get(_key(ctx))
    left, running = _remaining(timer, total)

    state = _shared.countdown_state(
        left, total, cfg,
        caption=str(cfg.get("label") or "Timer"),
        running=running,
        paused=bool(timer) and timer.get("state") == "paused",
    )
    ctx.state.clear()
    ctx.state.update(state)


def on_load(ctx: Any) -> None:
    render(ctx)


def on_poll(ctx: Any, interval: int = 1000) -> None:
    render(ctx)


def on_press(ctx: Any) -> None:
    """Cycle idle -> running -> paused -> running; a finished timer resets."""
    cfg = ctx.config
    total = parse_duration(cfg.get("duration", "5:00")) or 300.0
    timers = dict(_load(ctx))
    key = _key(ctx)
    timer = timers.get(key)
    left, running = _remaining(timer, total)

    if left <= 0:
        timers[key] = {"state": "idle", "remaining": total}
    elif running:
        timers[key] = {"state": "paused", "remaining": max(0.0, left)}
    else:
        timers[key] = {"state": "running", "ends_at": time.time() + left}

    _save(ctx, timers)
    render(ctx)
