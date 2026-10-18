"""Next Track — skip to the next Spotify track."""

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
SpotifyError = _shared.SpotifyError

_ICON = "assets/icons/Next.png"


def on_load(ctx: Any) -> None:
    ctx.state._template = "next_track"
    ctx.state.icon_src = _ICON


def on_press(ctx: Any) -> None:
    try:
        client = get_client(ctx)
        client.next_track()
    except Exception:
        evict_client(ctx)
