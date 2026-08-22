"""Volume Down — lowers the default sink by a configurable step."""

from __future__ import annotations

import sys
from typing import Any

from lib.plugin_id import python_import_module_name

_ICON = "assets/icons/VolumeDown.png"


def _shared(ctx: Any) -> Any:
    """The plugin's own `src/shared.py`, loaded once by the PDK runtime."""
    return sys.modules[python_import_module_name("pdk_plugin_", ctx.plugin_name)]


def _paint(ctx: Any) -> None:
    label = _shared(ctx).volume_label(ctx)
    ctx.state.volume_label = label
    # The glyph yields room only when there is a percentage to show.
    ctx.state.icon_class = "icon-sm" if label else "icon"


def on_load(ctx: Any) -> None:
    ctx.state._template = "volume_down"
    ctx.state.icon_src = _ICON
    ctx.state.volume_label = ""
    ctx.state.icon_class = "icon"


def on_poll(ctx: Any, interval: int = 3000) -> None:
    _paint(ctx)


def on_press(ctx: Any) -> None:
    shared = _shared(ctx)
    shared.volume("volume_down", shared.clamp_step(ctx.config.get("step_percent", 5)))
    _paint(ctx)
