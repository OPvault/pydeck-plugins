"""GPU Monitor — live GPU temperature and utilisation."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional, Tuple

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "pdk_sysmon_shared", str(_ROOT / "plugin.py"),
)
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

nvidia_info = _shared.nvidia_info
amd_info = _shared.amd_info
sysfs_gpu_info = _shared.sysfs_gpu_info
to_f = _shared.to_f
temp_color = _shared.temp_color
usage_color = _shared.usage_color
val_class = _shared.val_class
sub_class = _shared.sub_class
COLOR_OK = _shared.COLOR_OK


def on_load(ctx: Any) -> None:
    ctx.state.temp = "N/A"
    ctx.state.usage = ""
    ctx.state.bar_val = 0
    ctx.state.val_class = "value"
    ctx.state.sub_class = "sub"
    ctx.state.bar_color = COLOR_OK


def on_poll(ctx: Any, interval: int = 3000) -> None:
    backend = str(ctx.config.get("gpu_backend", "auto"))
    use_f = ctx.config.get("temp_unit", "C") == "F"
    show_usage = bool(ctx.config.get("show_usage", True))

    info: Optional[Tuple[float, float]] = None
    if backend in ("auto", "nvidia"):
        info = nvidia_info()
    if info is None and backend in ("auto", "amd"):
        info = amd_info()
    if info is None and backend in ("auto", "sysfs"):
        info = sysfs_gpu_info()

    if info is None:
        ctx.state.temp = "N/A"
        ctx.state.usage = ""
        ctx.state.bar_val = 0
        ctx.state.val_class = "value"
        ctx.state.sub_class = "sub"
        ctx.state.bar_color = COLOR_OK
        return

    temp_c, util_pct = info
    ctx.state.temp = f"{to_f(temp_c):.0f}°F" if use_f else f"{temp_c:.0f}°C"

    color = temp_color(temp_c)
    ctx.state.val_class = val_class(color)
    ctx.state.sub_class = sub_class(color)

    if show_usage:
        ctx.state.usage = f"{util_pct:.0f}%"
        ctx.state.bar_val = int(util_pct)
        ctx.state.bar_color = usage_color(util_pct)
    else:
        ctx.state.usage = ""
        ctx.state.bar_val = int(temp_c)
        ctx.state.bar_color = color
