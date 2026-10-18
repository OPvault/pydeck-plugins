"""Set Volume — set Spotify volume to a specific level (0–100%)."""

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

_ICON = "assets/icons/Volume.png"


def _vol_label(ctx: Any, vol: int | None) -> str:
    if not ctx.config.get("show_volume_label", False) or vol is None:
        return ""
    return f"{vol}%"


def on_load(ctx: Any) -> None:
    ctx.state._template = "set_volume"
    ctx.state.icon_src = _ICON
    ctx.state.volume_label = ""


def on_poll(ctx: Any, interval: int = 3000) -> None:
    if not ctx.config.get("show_volume_label", False):
        ctx.state.volume_label = ""
        return
    try:
        # Goes through the shared cache: free while another Spotify face on the
        # deck is already keeping the snapshot current, and one call per
        # interval when this button is the only one on it -- which is what the
        # old "read the file, fetch only if it is missing" did not do, leaving
        # a lone volume button showing whatever was true when it last fetched.
        pb = refresh_playback_state(get_client(ctx), ctx.storage_path, force=False)
        vol = (pb.get("device") or {}).get("volume_percent") if pb else None
        ctx.state.volume_label = _vol_label(ctx, vol)
    except Exception:
        pass


def on_press(ctx: Any) -> None:
    try:
        client = get_client(ctx)
        raw = ctx.config.get("volume_percent")
        if raw is None or raw == "":
            return
        target = max(0, min(100, int(raw)))
        client.set_volume(target)
        invalidate_pb_cache()
        ctx.state.volume_label = _vol_label(ctx, target)
    except Exception:
        evict_client(ctx)
