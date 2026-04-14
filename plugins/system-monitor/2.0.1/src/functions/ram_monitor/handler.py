"""RAM Monitor — live RAM usage percentage and optional used/total."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "pdk_sysmon_shared", str(_ROOT / "shared.py"),
)
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

ram_stats = _shared.ram_stats
usage_color = _shared.usage_color
val_class = _shared.val_class
sub_class = _shared.sub_class
COLOR_OK = _shared.COLOR_OK


def on_load(ctx: Any) -> None:
    ctx.state.pct = 0
    ctx.state.detail = ""
    ctx.state.val_class = "value-ok"
    ctx.state.sub_class = "sub"
    ctx.state.bar_color = COLOR_OK


def on_poll(ctx: Any, interval: int = 2000) -> None:
    backend = str(ctx.config.get("ram_backend", "auto"))
    show_used = bool(ctx.config.get("show_used", True))

    ram = ram_stats(backend)
    if ram is None:
        ctx.state.pct = 0
        ctx.state.detail = "ERR"
        ctx.state.val_class = "value"
        ctx.state.sub_class = "sub"
        ctx.state.bar_color = COLOR_OK
        return

    used_gib, total_gib, pct = ram
    ctx.state.pct = int(pct)
    color = usage_color(pct)

    if show_used:
        ctx.state.detail = f"{used_gib:.1f}/{total_gib:.0f}G"
    else:
        ctx.state.detail = ""

    ctx.state.val_class = val_class(color)
    ctx.state.sub_class = sub_class(color)
    ctx.state.bar_color = color
