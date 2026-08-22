"""Previous Track — `previous_track` over MPRIS via playerctl."""

from __future__ import annotations

import sys
from typing import Any

from lib.plugin_id import python_import_module_name

_ICON = "assets/icons/Previous.png"


def _shared(ctx: Any) -> Any:
    """The plugin's own `src/shared.py`, loaded once by the PDK runtime."""
    return sys.modules[python_import_module_name("pdk_plugin_", ctx.plugin_name)]


def on_load(ctx: Any) -> None:
    ctx.state._template = "previous_track"
    ctx.state.icon_src = _ICON


def on_press(ctx: Any) -> None:
    shared = _shared(ctx)
    shared.transport("previous_track", shared.player_arg(ctx))
