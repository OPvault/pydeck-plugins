"""PDK handler for `counter` — pending package updates across every installed manager."""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List

from lib.plugins.ids import python_import_module_name

_FLASH_S = 2.5
_flash: Dict[str, float] = {"until": 0.0, "text": ""}


def _shared() -> Any:
    return sys.modules[python_import_module_name("pdk_plugin_", "no.pydeck.updates")]


def _num(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def _ids(shared: Any, cfg: Dict[str, Any]) -> List[str]:
    ids = shared.selected_ids(cfg)
    shared.ensure_running(ids, _num(cfg.get("interval_minutes"), 30, 1, 1440))
    return ids


_OLD_DEFAULTS = {"color_ok": "#7ee787", "color_warn": "#ffd166", "color_crit": "#ff6b6b"}


def _status_colors(ctx: Any) -> tuple:
    """``(ok, warn, crit)``: the shared status colors, or the button's own when set to Custom.

    A button saved before the choice existed has no ``status_colors``; it counts
    as Custom only if someone changed one of its colors from the old defaults.
    """
    cfg = ctx.config
    mode = cfg.get("status_colors")
    if mode is None:
        mode = "custom" if any(
            str(cfg.get(k) or v).lower() != v for k, v in _OLD_DEFAULTS.items()
        ) else "global"
    if mode == "custom":
        return tuple(str(cfg.get(k) or v) for k, v in _OLD_DEFAULTS.items())
    prefs = ctx.preferences
    return (str(prefs.get("color_ok") or "#3fb950"),
            str(prefs.get("color_warn") or "#d29922"),
            str(prefs.get("color_crit") or "#f85149"))


def _render(ctx: Any) -> None:
    shared = _shared()
    cfg = ctx.config
    ids = _ids(shared, cfg)
    info = shared.summary(ids)
    total = info["total"]

    warn = int(_num(cfg.get("warn_at"), 10, 0, 100000))
    crit = int(_num(cfg.get("crit_at"), 50, 0, 100000))
    fg_ok, fg_warn, fg_crit = _status_colors(ctx)

    if not ids:
        count, tint, sub = "--", "#8b949e", "no managers"
    elif not info["known"]:
        count, tint, sub = "…", "#8b949e", "checking"
    else:
        count = str(total)
        if crit and total >= crit:
            tint = fg_crit
        elif warn and total >= warn:
            tint = fg_warn
        else:
            tint = fg_ok
        if info["errors"]:
            sub = info["errors"][0]
        elif shared.truthy(cfg.get("show_breakdown", True)) and info["parts"]:
            sub = " · ".join(info["parts"][:3])
        elif total == 0:
            sub = "up to date"
        else:
            sub = "pending"
        if info["checking"]:
            sub = "checking…"

    if time.monotonic() < _flash["until"]:
        sub = _flash["text"]

    ctx.state._template = "counter"
    ctx.state.label = str(cfg.get("label") if cfg.get("label") is not None else "Updates")
    ctx.state.count = count
    ctx.state.sub = sub
    ctx.state.tint = tint
    ctx.state.sub_c = "#ffb4b4" if (info["errors"] and info["known"]) else "rgba(255,255,255,0.7)"


def on_load(ctx: Any) -> None:
    _render(ctx)


def on_poll(ctx: Any, interval: int = 2000) -> None:
    _render(ctx)


def on_press(ctx: Any) -> None:
    shared = _shared()
    cfg = ctx.config
    ids = _ids(shared, cfg)
    action = str(cfg.get("press_action", "refresh"))

    if action in ("update", "both"):
        err = shared.run_updates(ids, str(cfg.get("terminal") or ""))
        _flash["text"] = err or "updating…"
        _flash["until"] = time.monotonic() + _FLASH_S
    if action in ("refresh", "both"):
        shared.refresh_now(ids)
        if action == "refresh":
            _flash["text"] = "refreshing…"
            _flash["until"] = time.monotonic() + _FLASH_S
    _render(ctx)
