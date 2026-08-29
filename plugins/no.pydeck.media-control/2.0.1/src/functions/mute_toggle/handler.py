"""Toggle Mute — the face follows the default sink's real mute state."""

from __future__ import annotations

import sys
from typing import Any

from lib.plugins.ids import python_import_module_name

_ICON_LIVE = "assets/icons/Volume.png"
_ICON_MUTED = "assets/icons/Mute.png"


def _shared(ctx: Any) -> Any:
    """The plugin's own `src/shared.py`, loaded once by the PDK runtime."""
    return sys.modules[python_import_module_name("pdk_plugin_", ctx.plugin_name)]


def _paint(ctx: Any) -> None:
    shared = _shared(ctx)
    muted = shared.is_muted()

    # An unreadable mixer (no pactl/amixer) draws the unmuted face rather
    # than a third "unknown" one — the button still works via xdotool.
    if muted:
        ctx.state.icon_src = shared.state_icon(ctx, "active", _ICON_MUTED)
        ctx.state.face_class = "face-muted"
    else:
        ctx.state.icon_src = shared.state_icon(ctx, "default", _ICON_LIVE)
        ctx.state.face_class = ""


def on_load(ctx: Any) -> None:
    ctx.state._template = "mute_toggle"
    ctx.state.icon_src = _ICON_LIVE
    ctx.state.face_class = ""


def on_poll(ctx: Any, interval: int = 3000) -> None:
    _paint(ctx)


def on_press(ctx: Any) -> None:
    _shared(ctx).volume("mute_toggle", 0)
    _paint(ctx)
