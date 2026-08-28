"""Battery Monitor -- charge, draw and estimated time left.

The threshold ramp runs the other way here: on a battery it is the *low* end
that is critical, so the gates are read inverted.
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

_HEADER = "Batt"
_SCOPE = "battery"

_STATUS_SHORT = {
    "charging": "Charging",
    "discharging": "On batt",
    "full": "Full",
    "not charging": "Idle",
    "unknown": "",
}


def _text(kind: str, info: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    decimals = bool(cfg.get("decimals", False))
    if kind == "charge":
        return _shared.fmt_pct(info.get("charge_pct"), decimals)
    if kind == "power":
        return _shared.fmt_watts(info.get("power_w")) or "--"
    if kind == "time":
        return _shared.fmt_duration(info.get("seconds_left")) or "--"
    if kind == "status":
        status = str(info.get("status") or "").strip()
        return _STATUS_SHORT.get(status.lower(), status)
    return ""


def render(ctx: Any, sample: bool = True) -> None:
    cfg = ctx.config
    info = _shared.battery_info()
    if info is None:
        ctx.state.clear()
        ctx.state.update(_shared.error_state(cfg, _HEADER))
        return

    charge = info.get("charge_pct")
    tint, gates = _shared.tint_for(
        cfg,
        reading=charge,
        warn=_shared.cfg_float(cfg, "warn_at", 30.0),
        crit=_shared.cfg_float(cfg, "crit_at", 15.0),
        invert=True,
    )

    key = _shared.history_key(cfg, _SCOPE)
    samples = (_shared.push_history(key, charge) if sample
               else _shared.read_history(key))

    ctx.state.clear()
    ctx.state.update(_shared.face_state(
        cfg,
        header=_HEADER,
        value=_text(str(cfg.get("primary", "charge")), info, cfg),
        sub=_text(str(cfg.get("sub_metric", "status")), info, cfg),
        bar_pct=charge,
        tint=tint, gates=gates, samples=samples,
    ))


def on_load(ctx: Any) -> None:
    render(ctx, sample=False)


def on_poll(ctx: Any, interval: int = 20000) -> None:
    render(ctx)


def on_press(ctx: Any) -> None:
    render(ctx)
