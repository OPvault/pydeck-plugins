"""Play / Pause — shows album art when playing, icon when idle."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
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
_last_pb: dict | None = None
# One extra call per track, when the local countdown says the song has ended.
_boundary_fetch_done: bool = False
# "Keep album art while paused": the face is held on the paused track, with the
# time left frozen where the pause left it.
_paused_hold: bool = False
_paused_remaining_ms: int = 0


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


def _playing_template(ctx: Any) -> str:
    """Now-playing face for the configured label position.

    "bottom" (default) keeps the original layout -- countdown on top, track
    label along the bottom edge.  "top" swaps the two rows.
    """
    pos = str(ctx.config.get("label_position") or "bottom").strip().lower()
    return "play_pause_label_top" if pos == "top" else "play_pause"


def _apply_playback(ctx: Any, pb: dict | None) -> None:
    """Apply fetched playback data to ctx.state.

    Only resets the local countdown timer when the track changes or
    playback was previously stopped.  For same-track refreshes, the
    API data updates art/label but the countdown keeps ticking locally.
    """
    global _countdown_start, _countdown_remaining_ms, _countdown_duration_ms
    global _countdown_active, _current_track_id, _last_pb, _boundary_fetch_done
    global _paused_hold, _paused_remaining_ms

    _last_pb = pb if isinstance(pb, dict) else None

    if not pb or not pb.get("is_playing", False):
        if _hold_paused_face(ctx, pb):
            return
        _paused_hold = False
        ctx.state._template = "play_pause_idle"
        ctx.state.idle_icon = _IDLE_ICON
        ctx.state.track_label = ""
        ctx.state.time_left = ""
        ctx.state.art_src = ""
        _countdown_active = False
        _current_track_id = ""
        return

    _paused_hold = False
    ctx.state._template = _playing_template(ctx)

    art = fetch_album_art(pb, ctx.storage_path)
    ctx.state.art_src = art or ""

    mode = ctx.config.get("display_mode", "song")
    ctx.state.track_label = build_track_label(pb, mode)

    item = pb.get("item") or {}
    duration_ms = int(item.get("duration_ms") or 0)
    progress_ms = int(pb.get("progress_ms") or 0)
    track_id = _track_id_from_pb(pb)

    if track_id != _current_track_id:
        _boundary_fetch_done = False

    # An exhausted countdown is re-seeded too: the same track can legitimately
    # report progress again (a seek back, a repeat), and leaving the timer at
    # zero would ask for a fresh call every second from then on.
    resync = (
        track_id != _current_track_id
        or not _countdown_active
        or _local_remaining() <= 0
    )

    if resync:
        _countdown_remaining_ms = max(0, duration_ms - progress_ms)
        _countdown_duration_ms = duration_ms
        _countdown_start = time.monotonic()
        _countdown_active = True
        _current_track_id = track_id

    ctx.state.time_left = _time_left_label(ctx)


def _hold_paused_face(ctx: Any, pb: dict | None) -> bool:
    """Keep the now-playing face through a pause, when the user asked for it.

    Only a track this process saw playing is held, and only while nothing
    says another one has taken its place: a paused snapshot naming a different
    track drops to the idle face as before. An empty snapshot keeps the hold --
    Spotify stops reporting a device some minutes into a pause, and the art
    should not vanish just because it did.
    """
    global _paused_hold, _paused_remaining_ms, _countdown_active

    if not _shared.keep_art_when_paused(ctx) or not _current_track_id:
        return False
    track_id = _track_id_from_pb(pb)
    if track_id and track_id != _current_track_id:
        return False

    if not _paused_hold:
        item = (pb or {}).get("item") or {}
        duration_ms = int(item.get("duration_ms") or 0)
        if pb and duration_ms:
            _paused_remaining_ms = max(0, duration_ms - int(pb.get("progress_ms") or 0))
        else:
            _paused_remaining_ms = _local_remaining()
    _paused_hold = True
    # Stopped, so a resume re-seeds the countdown from Spotify's progress.
    _countdown_active = False
    ctx.state._template = _playing_template(ctx)
    ctx.state.time_left = _time_left_label(ctx)
    return True


def _time_left_label(ctx: Any) -> str:
    show = ctx.config.get("show_time_left")
    if not (show is True or show == "true" or show == "on"):
        return ""
    remaining = _paused_remaining_ms if _paused_hold else _local_remaining()
    return _fmt_remaining(remaining) if remaining > 0 else ""


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
        pb = refresh_playback_state(client, _fetch_storage, force=False)
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


def _api_due(now: float) -> bool:
    """Whether this tick should cost a Spotify call.

    The face does not need one to stay alive -- the countdown below runs off a
    local timer -- so the interval is the one shared.py derives from what
    playback last said, and the only thing that shortens it is a track running
    out, which is the moment there is actually something new to read. Once per
    track: a paused or stalled countdown must not turn into a call a second.
    """
    global _boundary_fetch_done

    if _fetch_in_progress:
        return False
    if _last_fetch_time == 0.0:
        return True

    waited = now - _last_fetch_time
    if waited >= _shared.playback_poll_interval(_last_pb):
        return True

    if (
        not _boundary_fetch_done
        and _countdown_active
        and waited >= 1.0
        and _local_remaining() <= 0
    ):
        _boundary_fetch_done = True
        return True
    return False


def on_poll(ctx: Any, interval: int = 1000) -> None:
    global _fetch_ready, _pending_pb, _fetch_in_progress, _fetch_storage
    global _last_fetch_time

    # The background fetch has no ctx, so the interval is adopted here.
    _shared.configure(ctx)
    if _fetch_ready:
        _apply_playback(ctx, _pending_pb)
        _pending_pb = None
        _fetch_ready = False

    now = time.monotonic()
    if _api_due(now):
        _fetch_in_progress = True
        _fetch_storage = ctx.storage_path
        _last_fetch_time = now
        threading.Thread(target=_bg_fetch, daemon=True).start()

    ctx.state.time_left = _time_left_label(ctx)


def on_press(ctx: Any) -> None:
    global _countdown_active, _current_track_id, _last_fetch_time
    try:
        client = get_client(ctx)
        # Which endpoint to call depends on this answer, and a ten-second-old
        # snapshot can have the wrong one in it, so the press pays for a call.
        pb = refresh_playback_state(client, ctx.storage_path, force=True)

        if pb and pb.get("is_playing"):
            client.pause()
            _countdown_active = False
        else:
            _shared.start_playback(client, ctx)
            _current_track_id = ""

        invalidate_pb_cache()
        pb = refresh_playback_state(client, ctx.storage_path, force=True)
        _apply_playback(ctx, pb)
        # The press just paid for a fresh read; the poll interval starts here.
        _last_fetch_time = time.monotonic()
    except _shared.NoPlaybackDevice:
        # Nowhere to play is something the user can fix, so it is reported
        # rather than leaving a press that silently did nothing.
        raise
    except Exception:
        pass
