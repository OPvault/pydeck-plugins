"""RAM Monitor -- memory in use, what is left, and swap.

The bar always tracks memory usage, whichever reading the big value is set to.
"""

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

_HEADER = "RAM"
_SCOPE = "ram"


def _readings(cfg: Dict[str, Any], wanted: Set[str]) -> Optional[Dict[str, Any]]:
    ram = _shared.ram_stats(str(cfg.get("ram_backend", "auto")))
    if ram is None:
        return None
    used, total, pct = ram
    out: Dict[str, Any] = {
        "used": used, "total": total, "usage": pct,
        "avail": max(0.0, total - used), "swap": None,
    }
    if "swap" in wanted or "swap_pair" in wanted:
        out["swap"] = _shared.swap_stats()
    return out


def _text(kind: str, r: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    decimals = bool(cfg.get("decimals", False))
    if kind == "usage":
        return _shared.fmt_pct(r["usage"], decimals)
    if kind == "used":
        return _shared.fmt_size(r["used"])
    if kind == "avail":
        return _shared.fmt_size(r["avail"])
    if kind == "pair":
        return _shared.fmt_pair(r["used"], r["total"])
    if kind == "swap":
        return _shared.fmt_pct(r["swap"][2], decimals) if r["swap"] else "no swap"
    if kind == "swap_pair":
        return _shared.fmt_pair(r["swap"][0], r["swap"][1]) if r["swap"] else "no swap"
    return ""


def render(ctx: Any, sample: bool = True) -> None:
    cfg = ctx.config
    primary = str(cfg.get("primary", "usage"))
    sub_metric = str(cfg.get("sub_metric", "pair"))

    r = _readings(cfg, {primary, sub_metric})
    if r is None:
        ctx.state.clear()
        ctx.state.update(_shared.error_state(cfg, _HEADER, "ERR"))
        return

    tint, gates = _shared.tint_for(
        cfg,
        reading=r["usage"],
        warn=_shared.cfg_float(cfg, "warn_at", 70.0),
        crit=_shared.cfg_float(cfg, "crit_at", 90.0),
    )

    key = _shared.history_key(cfg, _SCOPE)
    samples = (_shared.push_history(key, r["usage"]) if sample
               else _shared.read_history(key))

    ctx.state.clear()
    ctx.state.update(_shared.face_state(
        cfg,
        header=_HEADER,
        value=_text(primary, r, cfg),
        sub=_text(sub_metric, r, cfg),
        bar_pct=r["usage"],
        tint=tint, gates=gates, samples=samples,
    ))


def on_load(ctx: Any) -> None:
    render(ctx, sample=False)


def on_poll(ctx: Any, interval: int = 2000) -> None:
    render(ctx)


def on_press(ctx: Any) -> None:
    render(ctx)
