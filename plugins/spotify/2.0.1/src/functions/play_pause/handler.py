"""Play / Pause — shows album art when playing, icon when idle."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
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
invalidate_pb_cache = _shared.invalidate_pb_cache
fetch_album_art = _shared.fetch_album_art
build_track_label = _shared.build_track_label
SpotifyError = _shared.SpotifyError

_IDLE_ICON = "assets/icons/PlayPause.png"

# Local countdown state — fully client-driven once seeded.
_countdown_start: float = 0.0      # monotonic time when local timer began
_countdown_remaining_ms: int = 0   # remaining ms at _countdown_start
_countdown_duration_ms: int = 0    # total song duration (for reference)
_countdown_active: bool = False
_current_track_id: str = ""

_pending_pb: dict | None = None
_fetch_ready: bool = False
_fetch_in_progress: bool = False
_fetch_storage: Path | None = None
_last_fetch_time: float = 0.0


def _fmt_remaining(remaining_ms: int) -> str:
    remaining_s = max(0, remaining_ms) // 1000
    mins = remaining_s // 60
    secs = remaining_s % 60
    return f"-{mins}:{secs:02d}"


def _track_id_from_pb(pb: dict | None) -> str:
    if not pb or not isinstance(pb, dict):
        return ""
    item = pb.get("item")
    if not isinstance(item, dict):
        return ""
    return str(item.get("id") or item.get("uri") or "")


def _apply_playback(ctx: Any, pb: dict | None) -> None:
    """Apply fetched playback data to ctx.state.

    Only resets the local countdown timer when the track changes or
    playback was previously stopped.  For same-track refreshes, the
    API data updates art/label but the countdown keeps ticking locally.
    """
    global _countdown_start, _countdown_remaining_ms, _countdown_duration_ms
    global _countdown_active, _current_track_id

    if not pb or not pb.get("is_playing", False):
        ctx.state._template = "play_pause_idle"
        ctx.state.idle_icon = _IDLE_ICON
        ctx.state.track_label = ""
        ctx.state.time_left = ""
        ctx.state.art_src = ""
        _countdown_active = False
        _current_track_id = ""
        return

    ctx.state._template = "play_pause"

    art = fetch_album_art(pb, ctx.storage_path)
    ctx.state.art_src = art or ""

    mode = ctx.config.get("display_mode", "song")
    ctx.state.track_label = build_track_label(pb, mode)

    item = pb.get("item") or {}
    duration_ms = int(item.get("duration_ms") or 0)
    progress_ms = int(pb.get("progress_ms") or 0)
    track_id = _track_id_from_pb(pb)

    resync = (
        track_id != _current_track_id
        or not _countdown_active
    )

    if resync:
        _countdown_remaining_ms = max(0, duration_ms - progress_ms)
        _countdown_duration_ms = duration_ms
        _countdown_start = time.monotonic()
        _countdown_active = True
        _current_track_id = track_id

    remaining = _local_remaining()
    show = ctx.config.get("show_time_left")
    if show is True or show == "true" or show == "on":
        ctx.state.time_left = _fmt_remaining(remaining) if remaining > 0 else ""
    else:
        ctx.state.time_left = ""


def _local_remaining() -> int:
    """Pure local countdown — no API needed after initial seed."""
    if not _countdown_active:
        return 0
    elapsed = time.monotonic() - _countdown_start
    return max(0, _countdown_remaining_ms - int(elapsed * 1000))


def _bg_fetch() -> None:
    """Run the Spotify API call in a background thread."""
    global _pending_pb, _fetch_ready, _fetch_in_progress
    try:
        client = get_client()
        pb = refresh_playback_state(client, _fetch_storage, force=True)
        _pending_pb = pb
    except Exception:
        _pending_pb = None
    _fetch_ready = True
    _fetch_in_progress = False


def on_load(ctx: Any) -> None:
    ctx.state._template = "play_pause_idle"
    ctx.state.idle_icon = _IDLE_ICON
    ctx.state.art_src = ""
    ctx.state.track_label = ""
    ctx.state.time_left = ""


def on_poll(ctx: Any, interval: int = 1000) -> None:
    global _fetch_ready, _pending_pb, _fetch_in_progress, _fetch_storage
    global _last_fetch_time

    if _fetch_ready:
        _apply_playback(ctx, _pending_pb)
        _pending_pb = None
        _fetch_ready = False

    now = time.monotonic()
    api_due = (now - _last_fetch_time) >= 3.0

    if api_due and not _fetch_in_progress:
        _fetch_in_progress = True
        _fetch_storage = ctx.storage_path
        _last_fetch_time = now
        threading.Thread(target=_bg_fetch, daemon=True).start()

    show = ctx.config.get("show_time_left")
    if show is True or show == "true" or show == "on":
        remaining = _local_remaining()
        ctx.state.time_left = _fmt_remaining(remaining) if remaining > 0 else ""
    else:
        ctx.state.time_left = ""


def on_press(ctx: Any) -> None:
    global _countdown_active, _current_track_id
    try:
        client = get_client(ctx)
        pb = refresh_playback_state(client, ctx.storage_path, force=False)

        if pb and pb.get("is_playing"):
            client.pause()
            _countdown_active = False
        else:
            client.play()
            _current_track_id = ""

        invalidate_pb_cache()
        pb = refresh_playback_state(client, ctx.storage_path, force=True)
        _apply_playback(ctx, pb)
    except Exception:
        pass
