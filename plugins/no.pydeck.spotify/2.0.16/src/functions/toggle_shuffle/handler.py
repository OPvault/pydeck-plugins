"""Toggle Shuffle — toggle Spotify shuffle mode on/off."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

# One copy of shared.py per process, not one per function: a second copy means
# a second playback cache, a second client and a second rate-limit window, so a
# deck with six Spotify buttons asked Spotify six times for the same second of
# playback. Reused only when it was loaded from this install, so an upgrade in
# place cannot leave a stale module behind.
_ROOT = Path(__file__).resolve().parent.parent.parent
_SHARED_PATH = _ROOT / "shared.py"
_shared = sys.modules.get("spotify_shared")
if getattr(_shared, "__file__", None) != str(_SHARED_PATH):
    _spec = importlib.util.spec_from_file_location("spotify_shared", str(_SHARED_PATH))
    _shared = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _shared
    _spec.loader.exec_module(_shared)

get_client = _shared.get_client
evict_client = _shared.evict_client
refresh_playback_state = _shared.refresh_playback_state
playback_from_state = _shared.playback_from_state
invalidate_pb_cache = _shared.invalidate_pb_cache
SpotifyError = _shared.SpotifyError

_ICON = "assets/icons/Shuffle.png"


def _set_status(ctx: Any, shuffle: bool | None) -> None:
    if shuffle is None:
        ctx.state.status_label = ""
        ctx.state.status_class = "status-off"
    elif shuffle:
        ctx.state.status_label = "ON"
        ctx.state.status_class = "status-on"
    else:
        ctx.state.status_label = "OFF"
        ctx.state.status_class = "status-off"


def on_load(ctx: Any) -> None:
    ctx.state._template = "toggle_shuffle"
    ctx.state.icon_src = _ICON
    ctx.state.status_label = ""
    ctx.state.status_class = "status-off"


def on_poll(ctx: Any, interval: int = 5000) -> None:
    try:
        # Goes through the shared cache: free while another Spotify face on the
        # deck is already keeping the snapshot current, and one call per
        # interval when this button is the only one on it -- which is what the
        # old "read the file, fetch only if it is missing" did not do, leaving
        # a lone volume button showing whatever was true when it last fetched.
        pb = refresh_playback_state(get_client(ctx), ctx.storage_path, force=False)
        shuffle = pb.get("shuffle_state") if pb else None
        _set_status(ctx, shuffle)
    except Exception:
        pass


def on_press(ctx: Any) -> None:
    try:
        client = get_client(ctx)
        pb = playback_from_state(ctx.storage_path) or refresh_playback_state(
            client, ctx.storage_path, force=False
        )
        current_shuffle = pb.get("shuffle_state", False) if pb else False
        client.set_shuffle(not current_shuffle)
        invalidate_pb_cache()
        _set_status(ctx, not current_shuffle)
    except Exception:
        evict_client(ctx)
