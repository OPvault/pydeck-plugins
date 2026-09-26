"""Shared utilities for the PDK Spotify plugin.

Provides SpotifyClient management, playback state caching, album art
downloading, and label formatting used by all per-function handlers.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PLUGIN_DIR = Path(__file__).parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from spotify_client import SpotifyClient, SpotifyError, _DEFAULT_REDIRECT_URI  # noqa: E402


def _resolve_redirect_uri() -> str:
    try:
        from lib.plugins import oauth as _oauth_lib
        return _oauth_lib.get_redirect_uri(PLUGIN_ID)
    except Exception:
        return _DEFAULT_REDIRECT_URI


_REDIRECT_URI = _resolve_redirect_uri()

_CREDS_PATH = Path.home() / ".config" / "pydeck" / "core" / "credentials.json"


def _core_store():
    """The core's credential store (PyDeck builds that keep state in pydeck.db).

    ``None`` on an older core, where credentials.json is still the store and
    the file paths below are the fallback.
    """
    try:
        from lib.plugins import credentials_store  # noqa: PLC0415
    except Exception:
        return None
    return credentials_store

# The core stores credentials under the RDNN id and only migrates the old
# slug on write, so both keys have to be honoured on read -- RDNN last so a
# migrated blob wins over a stale pre-RDNN one.
PLUGIN_ID = "no.pydeck.spotify"
_LEGACY_PLUGIN_ID = "spotify"

_client_cache: dict[tuple[str, str], SpotifyClient] = {}

_pb_cache: Optional[dict] = None
_pb_cache_ts: float = 0.0

# How long a playback snapshot is worth reusing, by what it says.
#
# Every one of these calls is counted against the app's Spotify quota, and an
# app that runs over it is refused for the better part of an hour -- so the
# budget is spent where it buys something. Almost nothing on the face needs a
# fresh call: play_pause runs its own countdown locally and asks for one call
# when a track runs out, and the volume/shuffle/repeat faces read the snapshot
# this module writes instead of fetching their own. What a call actually buys
# is noticing a change made somewhere else -- a skip from the phone, a pause in
# the desktop app -- which is worth seconds, not one second.
_TTL_PLAYING = 10.0
_TTL_PAUSED = 15.0
_TTL_STOPPED = 30.0
# A forced refresh (straight after a press) still rides a snapshot this fresh,
# so the press and the poll that follows it do not both pay for a call.
_TTL_FORCED = 1.0
# Spotify's Retry-After can be the better part of an hour; honour it, but never
# lock the plugin out for longer than that on one refusal.
_MAX_BACKOFF = 3600.0

_last_art_url: Optional[str] = None
# Wall clock of the last playback change this process made; a published
# snapshot older than this describes the state before it.
_invalidated_at: float = 0.0
# Wall clock, not monotonic: the window is shared with the other process
# through state.json, and only wall clock means the same thing in both.
_rate_limited_until: float = 0.0


def _load_credentials(ctx: Any = None) -> Dict[str, Any]:
    """Load the plugin's credentials.

    The core's store is the source (it merges the legacy slug and the RDNN
    id itself); ``ctx.credentials`` overlays it when present. On a core that
    still keeps credentials.json, the file is read directly instead, because
    its hardware listener dispatches poll without credentials.
    """
    merged: Dict[str, Any] = {}
    store = _core_store()
    try:
        if store is not None:
            merged.update(store.load(PLUGIN_ID))
        elif _CREDS_PATH.is_file():
            raw = json.loads(_CREDS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in (_LEGACY_PLUGIN_ID, PLUGIN_ID):
                    entry = raw.get(key)
                    if isinstance(entry, dict):
                        merged.update(entry)
    except Exception:
        pass
    if ctx is not None:
        ctx_creds = getattr(ctx, "credentials", None)
        if isinstance(ctx_creds, dict):
            merged.update({k: v for k, v in ctx_creds.items() if v})
    return merged


def _set_rate_limit_from_error(err: Any) -> None:
    """Open a back-off window from whatever the client reported.

    ``SpotifyError.retry_after`` is the real answer; the message is parsed only
    for an older client that carried the seconds in its text.
    """
    global _rate_limited_until
    wait_s = getattr(err, "retry_after", None)
    if wait_s is None:
        msg = str(err or "")
        if "429" not in msg:
            return
        wait_s = 60.0
        m = re.search(r"Retry-After:\s*(\d+(?:\.\d+)?)", msg)
        if m:
            try:
                wait_s = float(m.group(1))
            except (TypeError, ValueError):
                wait_s = 60.0
    try:
        wait_s = max(1.0, min(float(wait_s), _MAX_BACKOFF))
    except (TypeError, ValueError):
        wait_s = 60.0
    _rate_limited_until = max(_rate_limited_until, time.time() + wait_s)


def _note_shared_rate_limit(until: float) -> None:
    """Adopt a window the other process opened."""
    global _rate_limited_until
    try:
        until = float(until)
    except (TypeError, ValueError):
        return
    if until > _rate_limited_until:
        _rate_limited_until = min(until, time.time() + _MAX_BACKOFF)


def _is_rate_limited() -> bool:
    return time.time() < _rate_limited_until


def rate_limited_for() -> float:
    """Seconds left on the back-off window, 0 when there is none."""
    return max(0.0, _rate_limited_until - time.time())


# "Check Spotify every" from Settings -> Plugin settings. It replaces the
# playing and paused windows alike -- a paused session is exactly when a resume
# from the phone should be noticed -- but never shortens the stopped one, which
# is the idle cost of having the plugin installed at all.
_MIN_POLL = 3.0
_poll_every: Optional[float] = None


def configure(ctx: Any) -> None:
    """Adopt the plugin-wide settings carried on *ctx*.

    ``getattr``: a PyDeck from before plugin settings has no ``ctx.settings``,
    and there the built-in windows stay in force.
    """
    global _poll_every
    settings = getattr(ctx, "settings", None) or {}
    try:
        value = float(settings["update_interval"])
    except (KeyError, TypeError, ValueError):
        _poll_every = None
        return
    _poll_every = max(_MIN_POLL, value)


def keep_art_when_paused(ctx: Any) -> bool:
    settings = getattr(ctx, "settings", None) or {}
    return bool(settings.get("keep_art_when_paused", False))


def playback_poll_interval(pb: Optional[dict]) -> float:
    """How long to wait before asking Spotify again, given what it last said."""
    if not isinstance(pb, dict) or not pb:
        return max(_TTL_STOPPED, _poll_every or 0.0)
    if _poll_every is not None:
        return _poll_every
    return _TTL_PLAYING if pb.get("is_playing") else _TTL_PAUSED


def _state_file(storage_dir: Path) -> Path:
    return storage_dir / "state.json"


def _read_state_payload(storage_dir: Path) -> dict:
    sf = _state_file(storage_dir)
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state_payload(storage_dir: Path, pb: Optional[dict], error: str = "") -> None:
    """Publish the snapshot other readers work from.

    This file is the only thing the two PyDeck processes have in common: the
    server renders the web grid and the listener subprocess renders the deck,
    each with its own copy of this module, so without it the same second of
    playback is bought twice. ``rate_limited_until`` travels the same way --
    a refusal one process earned is one the other must respect.
    """
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": time.time(),
            "playback": pb if isinstance(pb, dict) else None,
            "error": str(error or ""),
            "rate_limited_until": _rate_limited_until,
        }
        _state_file(storage_dir).write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def playback_from_state(storage_dir: Path) -> Optional[dict]:
    payload = _read_state_payload(storage_dir)
    pb = payload.get("playback")
    return pb if isinstance(pb, dict) else None


def _shared_snapshot(storage_dir: Path) -> Tuple[Optional[dict], Optional[float]]:
    """The published snapshot and its age in seconds, adopting any back-off.

    The age is ``None`` when there is no snapshot, or when its timestamp is
    unusable -- a wall clock that moved backwards would otherwise make a stale
    file look like it arrived in the future.
    """
    payload = _read_state_payload(storage_dir)
    if not payload:
        return None, None
    _note_shared_rate_limit(payload.get("rate_limited_until") or 0.0)
    pb = payload.get("playback")
    pb = pb if isinstance(pb, dict) else None
    try:
        age = time.time() - float(payload.get("updated_at") or 0.0)
    except (TypeError, ValueError):
        return pb, None
    if age < 0 or age > _MAX_BACKOFF:
        return pb, None
    if float(payload.get("updated_at") or 0.0) <= _invalidated_at:
        return pb, None
    return pb, age


def refresh_playback_state(
    client: SpotifyClient, storage_dir: Path, force: bool = False
) -> Optional[dict]:
    """Current playback, from a cache where possible and the API where not.

    *force* shortens the window rather than removing it: a press wants the
    freshest state it can get, but not at the price of a second call for a
    snapshot that is one second old.
    """
    global _pb_cache, _pb_cache_ts

    now = time.monotonic()
    ttl = _TTL_FORCED if force else playback_poll_interval(_pb_cache)
    if _pb_cache is not None and (now - _pb_cache_ts) < ttl:
        return _pb_cache

    shared_pb, shared_age = _shared_snapshot(storage_dir)
    if shared_age is not None:
        shared_ttl = _TTL_FORCED if force else playback_poll_interval(shared_pb)
        if shared_age < shared_ttl:
            _pb_cache = shared_pb
            _pb_cache_ts = now - shared_age
            return shared_pb

    if _is_rate_limited():
        return _pb_cache if _pb_cache is not None else shared_pb

    try:
        pb = client.get_playback()
        _pb_cache = pb
        _pb_cache_ts = time.monotonic()
        _write_state_payload(storage_dir, pb)
        return pb
    except Exception as exc:
        _set_rate_limit_from_error(exc)
        fallback = _pb_cache if _pb_cache is not None else shared_pb
        _write_state_payload(storage_dir, fallback, str(exc))
        return fallback


def invalidate_pb_cache() -> None:
    """Drop the snapshot after changing playback ourselves.

    It also stamps the moment, so the refresh that follows does not adopt the
    snapshot the *other* process published a moment before the press -- that
    one describes the state we just changed, and is wrong in the same way the
    local cache was.
    """
    global _pb_cache, _pb_cache_ts, _invalidated_at
    _pb_cache = None
    _pb_cache_ts = 0.0
    _invalidated_at = time.time()


def get_client(ctx: Any = None) -> SpotifyClient:
    """Return a cached SpotifyClient, loading credentials from the core's store."""
    if ctx is not None:
        configure(ctx)
    creds = _load_credentials(ctx)
    cid = str(creds.get("client_id") or "").strip()
    csec = str(creds.get("client_secret") or "").strip()
    if not cid or not csec:
        raise SpotifyError(
            "client_id and client_secret are required — "
            "configure them under Settings → API"
        )
    key = (cid, csec)
    client = _client_cache.get(key)
    if client is None:
        client = SpotifyClient(
            cid, csec,
            access_token=str(creds.get("access_token") or "").strip(),
            refresh_token=str(creds.get("refresh_token") or "").strip(),
            redirect_uri=_REDIRECT_URI,
            creds_key=PLUGIN_ID,
        )
        _client_cache[key] = client
    else:
        at = str(creds.get("access_token") or "").strip()
        rt = str(creds.get("refresh_token") or "").strip()
        if at and not client.access_token:
            client.access_token = at
        if rt and not client.refresh_token:
            client.refresh_token = rt
    return client


def evict_client(ctx: Any = None) -> None:
    """Remove all cached clients so the next call creates a fresh one."""
    _client_cache.clear()


# ---------------------------------------------------------------------------
# Album art
# ---------------------------------------------------------------------------

def _pick_art_url(images: list) -> str:
    if not images:
        return ""
    suitable = [i for i in images if (i.get("height") or 0) >= 80]
    if suitable:
        suitable.sort(key=lambda i: i.get("height", 0))
        return suitable[0]["url"]
    return images[0]["url"]


def playback_art_url(pb: Optional[dict]) -> Optional[str]:
    if not pb or not isinstance(pb, dict):
        return None
    item = pb.get("item")
    if not isinstance(item, dict):
        return None
    album = item.get("album")
    if not isinstance(album, dict):
        return None
    images = album.get("images")
    if not images:
        return None
    url = _pick_art_url(images)
    return url if url else None


def fetch_album_art(pb: Optional[dict], storage_dir: Path) -> Optional[str]:
    """Download album art and return relative src path for templates, or None."""
    global _last_art_url

    art_url = playback_art_url(pb)
    if not art_url:
        return None

    art_file = storage_dir / "_now_playing.jpg"
    rel_path = "_now_playing.jpg"

    if art_url == _last_art_url and art_file.exists():
        return rel_path

    try:
        req = urllib.request.Request(art_url, headers={"User-Agent": "PyDeck/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
        if len(data) < 100:
            return None
        storage_dir.mkdir(parents=True, exist_ok=True)
        art_file.write_bytes(data)
        _last_art_url = art_url
        return rel_path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Label formatting
# ---------------------------------------------------------------------------

def build_track_label(pb: Optional[dict], mode: str = "song") -> str:
    if mode == "none" or not pb or not isinstance(pb, dict):
        return ""
    item = pb.get("item")
    if not isinstance(item, dict):
        return ""
    song = item.get("name", "") or ""
    artists_list = item.get("artists")
    artist = ""
    if isinstance(artists_list, list) and artists_list:
        artist = artists_list[0].get("name", "") or ""
    if mode == "artist":
        return artist
    if mode == "song_artist" and song and artist:
        return f"{song} - {artist}"
    return song


def format_time_left(pb: Optional[dict]) -> str:
    if not pb or not isinstance(pb, dict):
        return ""
    item = pb.get("item")
    if not isinstance(item, dict):
        return ""
    duration_ms = item.get("duration_ms")
    progress_ms = pb.get("progress_ms")
    if duration_ms is None or progress_ms is None:
        return ""
    try:
        remaining_ms = max(0, int(duration_ms) - int(progress_ms))
        remaining_s = remaining_ms // 1000
        mins = remaining_s // 60
        secs = remaining_s % 60
        return f"-{mins}:{secs:02d}"
    except (TypeError, ValueError):
        return ""
