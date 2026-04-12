"""CPU Monitor — live CPU usage percentage and optional temperature."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "pdk_sysmon_shared", str(_ROOT / "plugin.py"),
)
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

cpu_pct = _shared.cpu_pct
cpu_temp_c = _shared.cpu_temp_c
to_f = _shared.to_f
usage_color = _shared.usage_color
temp_color = _shared.temp_color
val_class = _shared.val_class
sub_class = _shared.sub_class
COLOR_OK = _shared.COLOR_OK


def on_load(ctx: Any) -> None:
    ctx.state.pct = 0
    ctx.state.temp = ""
    ctx.state.val_class = "value-ok"
    ctx.state.sub_class = "sub"
    ctx.state.bar_color = COLOR_OK


def on_poll(ctx: Any, interval: int = 2000) -> None:
    backend = str(ctx.config.get("cpu_backend", "auto"))
    show_temp = bool(ctx.config.get("show_temp", True))
    use_f = ctx.config.get("temp_unit", "C") == "F"

    pct = cpu_pct(backend)
    if pct is None:
        ctx.state.pct = 0
        ctx.state.temp = "ERR"
        ctx.state.val_class = "value"
        ctx.state.sub_class = "sub"
        ctx.state.bar_color = COLOR_OK
        return

    ctx.state.pct = int(pct)
    color = usage_color(pct)

    if show_temp:
        tc = cpu_temp_c()
        if tc is not None:
            ctx.state.temp = f"{to_f(tc):.0f}°F" if use_f else f"{tc:.0f}°C"
            color = temp_color(tc)
        else:
            ctx.state.temp = ""
    else:
        ctx.state.temp = ""

    ctx.state.val_class = val_class(color)
    ctx.state.sub_class = sub_class(color)
    ctx.state.bar_color = color
