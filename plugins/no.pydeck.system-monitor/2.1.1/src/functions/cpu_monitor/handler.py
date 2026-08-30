"""CPU Monitor -- usage, temperature, clock speed and load average.

The bar always tracks usage, whichever reading the big value is set to, so a
row of CPU keys stays comparable at a glance.
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

_HEADER = "CPU"
_SCOPE = "cpu"


def _readings(cfg: Dict[str, Any], wanted: Set[str]) -> Dict[str, Any]:
    """Read usage, plus whatever else this button's settings ask to show."""
    out: Dict[str, Any] = {
        "usage": _shared.cpu_pct(str(cfg.get("cpu_backend", "auto"))),
        "temp": None, "load": None, "freq": None, "cores": None, "uptime": None,
    }
    if "temp" in wanted:
        out["temp"] = _shared.cpu_temp_c()
    if "load" in wanted:
        out["load"] = _shared.load_avg()
    if "freq" in wanted:
        out["freq"] = _shared.cpu_freq_mhz()
    if "cores" in wanted:
        out["cores"] = _shared.cpu_core_count()
    if "uptime" in wanted:
        out["uptime"] = _shared.uptime_seconds()
    return out


def _text(kind: str, r: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    decimals = bool(cfg.get("decimals", False))
    if kind == "usage":
        return _shared.fmt_pct(r["usage"], decimals)
    if kind == "temp":
        return _shared.fmt_temp(r["temp"], cfg.get("temp_unit", "C") == "F") or "--"
    if kind == "load":
        return f"{r['load'][0]:.2f}" if r["load"] else "--"
    if kind == "freq":
        return _shared.fmt_freq(r["freq"])
    if kind == "cores":
        return f"{r['cores']} cores" if r["cores"] else "--"
    if kind == "uptime":
        return _shared.fmt_duration(r["uptime"]) or "--"
    return ""


def render(ctx: Any, sample: bool = True) -> None:
    cfg = ctx.config
    primary = str(cfg.get("primary", "usage"))
    sub_metric = str(cfg.get("sub_metric", "temp"))
    wanted = {primary, sub_metric}
    if str(cfg.get("tint", "auto")) == "temp":
        wanted.add("temp")

    r = _readings(cfg, wanted)
    tint, gates = _shared.tint_for(
        cfg,
        reading=r["usage"], temp_c=r["temp"],
        warn=_shared.cfg_float(cfg, "warn_at", 60.0),
        crit=_shared.cfg_float(cfg, "crit_at", 85.0),
        temp_warn=_shared.cfg_float(cfg, "temp_warn_at", 65.0),
        temp_crit=_shared.cfg_float(cfg, "temp_crit_at", 85.0),
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
