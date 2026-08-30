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


def _render(ctx: Any) -> None:
    shared = _shared()
    cfg = ctx.config
    ids = _ids(shared, cfg)
    info = shared.summary(ids)
    total = info["total"]

    warn = int(_num(cfg.get("warn_at"), 10, 0, 100000))
    crit = int(_num(cfg.get("crit_at"), 50, 0, 100000))
    fg_ok = str(cfg.get("color_ok") or "#7ee787")
    fg_warn = str(cfg.get("color_warn") or "#ffd166")
    fg_crit = str(cfg.get("color_crit") or "#ff6b6b")

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
