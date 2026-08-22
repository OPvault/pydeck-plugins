"""Play / Pause — the glyph follows the player's real MPRIS status."""

from __future__ import annotations

import sys
from typing import Any

from lib.plugin_id import python_import_module_name

# Playing -> offer Pause, otherwise offer Play. The combined PlayPause glyph
# is the fallback for when no player answers at all.
_ICON_PLAY = "assets/icons/Play.png"
_ICON_PAUSE = "assets/icons/Pause.png"
_ICON_IDLE = "assets/icons/PlayPause.png"


def _shared(ctx: Any) -> Any:
    """The plugin's own `src/shared.py`, loaded once by the PDK runtime."""
    return sys.modules[python_import_module_name("pdk_plugin_", ctx.plugin_name)]


def _paint(ctx: Any) -> None:
    shared = _shared(ctx)
    player = shared.player_arg(ctx)
    status, _title, _artist = shared.probe_player(player)

    if status == "playing":
        ctx.state.icon_src = _ICON_PAUSE
    elif status:
        ctx.state.icon_src = _ICON_PLAY
    else:
        ctx.state.icon_src = _ICON_IDLE

    label = shared.track_label(player, str(ctx.config.get("track_label", "none")))
    ctx.state.track_label = label
    ctx.state._template = "play_pause-track" if label else "play_pause"


def on_load(ctx: Any) -> None:
    ctx.state._template = "play_pause"
    ctx.state.icon_src = _ICON_IDLE
    ctx.state.track_label = ""


def on_poll(ctx: Any, interval: int = 2000) -> None:
    _paint(ctx)


def on_press(ctx: Any) -> None:
    shared = _shared(ctx)
    shared.transport("play_pause", shared.player_arg(ctx))
    _paint(ctx)
