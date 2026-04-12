"""Previous Track — go back to the previous Spotify track."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("spotify_shared", str(_ROOT / "plugin.py"))
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

get_client = _shared.get_client
evict_client = _shared.evict_client
SpotifyError = _shared.SpotifyError

_ICON = "img/Previous.png"


def on_load(ctx: Any) -> None:
    ctx.state._template = "prev_track"
    ctx.state.icon_src = _ICON


def on_press(ctx: Any) -> None:
    try:
        client = get_client(ctx)
        client.prev_track()
    except Exception:
        evict_client(ctx)
