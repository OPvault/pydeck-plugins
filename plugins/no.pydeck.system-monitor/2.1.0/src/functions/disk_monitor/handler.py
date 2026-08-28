"""Disk Monitor -- how full a mount point is, and what is left on it."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set

# PDK function modules are imported through an explicit spec, so the plugin's
# source directory never lands on sys.path -- load the shared module by path.
_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "pdk_sysmon_shared", str(_ROOT / "shared.py"),
)
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

_HEADER = "Disk"
_SCOPE = "disk"


def _mount(cfg: Dict[str, Any]) -> str:
    return str(cfg.get("path") or "/").strip() or "/"


def _text(kind: str, r: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    decimals = bool(cfg.get("decimals", False))
    if kind == "usage":
        return _shared.fmt_pct(r["usage"], decimals)
    if kind == "used":
        return _shared.fmt_size(r["used"])
    if kind == "free":
        return _shared.fmt_size(r["free"])
    if kind == "pair":
        return _shared.fmt_pair(r["used"], r["total"])
    if kind == "total":
        return _shared.fmt_size(r["total"])
    if kind == "mount":
        return r["mount"]
    return ""


def render(ctx: Any, sample: bool = True) -> None:
    cfg = ctx.config
    mount = _mount(cfg)
    stats = _shared.disk_stats(mount, str(cfg.get("disk_backend", "auto")))
    if stats is None:
        ctx.state.clear()
        ctx.state.update(_shared.error_state(cfg, _HEADER, "ERR"))
        return

    used, total, pct = stats
    r = {"used": used, "total": total, "usage": pct,
         "free": max(0.0, total - used), "mount": mount}

    tint, gates = _shared.tint_for(
        cfg,
        reading=pct,
        warn=_shared.cfg_float(cfg, "warn_at", 75.0),
        crit=_shared.cfg_float(cfg, "crit_at", 90.0),
    )

    key = _shared.history_key(cfg, _SCOPE)
    samples = (_shared.push_history(key, pct) if sample
               else _shared.read_history(key))

    ctx.state.clear()
    ctx.state.update(_shared.face_state(
        cfg,
        header=_HEADER,
        value=_text(str(cfg.get("primary", "usage")), r, cfg),
        sub=_text(str(cfg.get("sub_metric", "pair")), r, cfg),
        bar_pct=pct,
        tint=tint, gates=gates, samples=samples,
    ))


def on_load(ctx: Any) -> None:
    render(ctx, sample=False)


def on_poll(ctx: Any, interval: int = 10000) -> None:
    render(ctx)


def on_press(ctx: Any) -> None:
    render(ctx)
