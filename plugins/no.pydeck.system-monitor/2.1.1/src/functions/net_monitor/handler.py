"""Network Monitor -- live download and upload rates.

A rate is a difference, so the first poll after a load has nothing to subtract
from and reads zero.  The bar is a percentage of the full-scale rate the user
sets, because there is no natural ceiling to measure a link against.
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

_HEADER = "Net"
_SCOPE = "net"


def _text(kind: str, r: Dict[str, Any], bits: bool) -> str:
    if kind == "down":
        return _shared.fmt_rate(r["down"], bits)
    if kind == "up":
        return _shared.fmt_rate(r["up"], bits)
    if kind == "total":
        return _shared.fmt_rate(r["down"] + r["up"], bits)
    if kind == "iface":
        return r["iface"] or "all"
    return ""


def _full_scale_bytes(cfg: Dict[str, Any], bits: bool) -> float:
    """Bytes per second the bar reads as full, from the user's Mbit/MB field."""
    scale = _shared.cfg_float(cfg, "scale", 100.0)
    if scale <= 0:
        scale = 100.0
    return scale * 1e6 / 8.0 if bits else scale * float(1024 ** 2)


def render(ctx: Any, sample: bool = True) -> None:
    cfg = ctx.config
    iface = str(cfg.get("interface") or "").strip()
    bits = str(cfg.get("units", "bytes")) == "bits"

    key = _shared.history_key(cfg, _SCOPE)
    rates = _shared.net_rates(key, iface)
    if rates is None:
        ctx.state.clear()
        ctx.state.update(_shared.error_state(cfg, _HEADER))
        return

    down, up = rates
    r = {"down": down, "up": up, "iface": iface}

    primary = str(cfg.get("primary", "down"))
    tracked = {"down": down, "up": up}.get(primary, down + up)
    pct = _shared.clamp(tracked / _full_scale_bytes(cfg, bits) * 100.0, 0.0, 100.0)

    tint, gates = _shared.tint_for(
        cfg,
        reading=pct,
        warn=_shared.cfg_float(cfg, "warn_at", 60.0),
        crit=_shared.cfg_float(cfg, "crit_at", 85.0),
    )

    samples = (_shared.push_history(key + ":plot", pct) if sample
               else _shared.read_history(key + ":plot"))

    ctx.state.clear()
    ctx.state.update(_shared.face_state(
        cfg,
        header=_HEADER,
        value=_text(primary, r, bits),
        sub=_text(str(cfg.get("sub_metric", "up")), r, bits),
        bar_pct=pct,
        tint=tint, gates=gates, samples=samples,
    ))


def on_load(ctx: Any) -> None:
    render(ctx, sample=False)


def on_poll(ctx: Any, interval: int = 2000) -> None:
    render(ctx)


def on_press(ctx: Any) -> None:
    render(ctx)
