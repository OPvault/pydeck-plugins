"""Cycle Repeat — cycle Spotify repeat mode: off → context → track → off."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("spotify_shared", str(_ROOT / "shared.py"))
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

get_client = _shared.get_client
evict_client = _shared.evict_client
refresh_playback_state = _shared.refresh_playback_state
playback_from_state = _shared.playback_from_state
invalidate_pb_cache = _shared.invalidate_pb_cache
SpotifyError = _shared.SpotifyError

_ICON = "assets/icons/Repeat.png"
_REPEAT_LABELS = {"off": "OFF", "context": "ALL", "track": "ONE"}
_CYCLE = {"off": "context", "context": "track", "track": "off"}


def _set_status(ctx: Any, repeat: str | None) -> None:
    if repeat is None or repeat == "off":
        ctx.state.status_label = _REPEAT_LABELS.get(repeat or "off", "OFF")
        ctx.state.status_class = "status-off"
    else:
        ctx.state.status_label = _REPEAT_LABELS.get(repeat, repeat.upper())
        ctx.state.status_class = "status-on"


def on_load(ctx: Any) -> None:
    ctx.state._template = "cycle_repeat"
    ctx.state.icon_src = _ICON
    ctx.state.status_label = ""
    ctx.state.status_class = "status-off"


def on_poll(ctx: Any, interval: int = 5000) -> None:
    try:
        pb = playback_from_state(ctx.storage_path)
        if pb is None:
            client = get_client(ctx)
            pb = refresh_playback_state(client, ctx.storage_path, force=False)
        repeat = pb.get("repeat_state") if pb else None
        _set_status(ctx, repeat)
    except Exception:
        pass


def on_press(ctx: Any) -> None:
    try:
        client = get_client(ctx)
        pb = playback_from_state(ctx.storage_path) or refresh_playback_state(
            client, ctx.storage_path, force=False
        )
        current = pb.get("repeat_state", "off") if pb else "off"
        next_state = _CYCLE.get(current, "off")
        client.set_repeat(next_state)
        invalidate_pb_cache()
        _set_status(ctx, next_state)
    except Exception:
        evict_client(ctx)
