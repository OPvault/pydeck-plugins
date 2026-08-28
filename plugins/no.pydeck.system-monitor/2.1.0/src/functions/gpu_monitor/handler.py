"""GPU Monitor -- utilisation, temperature, VRAM and board power.

Laid out like the CPU, RAM and Disk readouts: the big value is the utilisation
percentage and the sub line carries the temperature, not the other way round.
The bar tracks utilisation whichever reading the big value is set to.
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

_HEADER = "GPU"
_SCOPE = "gpu"

# Board names arrive long enough to shrink a sub line to nothing; the vendor
# and product-line words carry no information once the header already says GPU.
_NAME_NOISE = ("NVIDIA ", "AMD ", "Radeon ", "GeForce ", "Intel(R) ", "Intel ")


def _short_name(name: str) -> str:
    out = str(name or "").strip()
    for word in _NAME_NOISE:
        out = out.replace(word, "")
    return out.strip()


def _text(kind: str, info: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    decimals = bool(cfg.get("decimals", False))
    if kind == "usage":
        return _shared.fmt_pct(info.get("util_pct"), decimals)
    if kind == "temp":
        return _shared.fmt_temp(
            info.get("temp_c"), cfg.get("temp_unit", "C") == "F"
        ) or "--"
    if kind == "mem":
        used, total = info.get("mem_used_gib"), info.get("mem_total_gib")
        if used is not None and total is not None:
            return _shared.fmt_pair(used, total)
        # rocm-smi reports VRAM as a percentage and gives no byte total.
        return _shared.fmt_pct(info.get("mem_pct"), decimals) if info.get("mem_pct") is not None else "--"
    if kind == "power":
        return _shared.fmt_watts(info.get("power_w")) or "--"
    if kind == "name":
        return _short_name(info.get("name", "")) or "--"
    return ""


def render(ctx: Any, sample: bool = True) -> None:
    cfg = ctx.config
    index = int(_shared.cfg_float(cfg, "gpu_index", 0.0))
    info = _shared.gpu_info(str(cfg.get("gpu_backend", "auto")), index)
    if info is None:
        ctx.state.clear()
        ctx.state.update(_shared.error_state(cfg, _HEADER))
        return

    usage = info.get("util_pct")
    tint, gates = _shared.tint_for(
        cfg,
        reading=usage, temp_c=info.get("temp_c"),
        warn=_shared.cfg_float(cfg, "warn_at", 60.0),
        crit=_shared.cfg_float(cfg, "crit_at", 85.0),
        temp_warn=_shared.cfg_float(cfg, "temp_warn_at", 70.0),
        temp_crit=_shared.cfg_float(cfg, "temp_crit_at", 85.0),
    )

    key = _shared.history_key(cfg, _SCOPE)
    samples = (_shared.push_history(key, usage) if sample
               else _shared.read_history(key))

    ctx.state.clear()
    ctx.state.update(_shared.face_state(
        cfg,
        header=_HEADER,
        value=_text(str(cfg.get("primary", "usage")), info, cfg),
        sub=_text(str(cfg.get("sub_metric", "temp")), info, cfg),
        bar_pct=usage,
        tint=tint, gates=gates, samples=samples,
    ))


def on_load(ctx: Any) -> None:
    render(ctx, sample=False)


def on_poll(ctx: Any, interval: int = 3000) -> None:
    render(ctx)


def on_press(ctx: Any) -> None:
    render(ctx)
