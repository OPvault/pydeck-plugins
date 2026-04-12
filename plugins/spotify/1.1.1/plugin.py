"""Spotify plugin for PyDeck.

Controls Spotify playback via the Web API (OAuth2 Authorization Code flow).

First-time setup:
1. Create a Spotify app at https://developer.spotify.com/dashboard
2. Add http://localhost:8686/oauth/spotify/callback as a Redirect URI in the app settings
3. Enter your Client ID and Client Secret under Settings → API (open Settings from the deck header)
4. Click Authorize there to complete OAuth
5. Spotify will redirect back automatically
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

_PLUGIN_DIR = Path(__file__).parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from spotify_client import SpotifyClient, SpotifyError, _DEFAULT_REDIRECT_URI  # noqa: E402


def _resolve_redirect_uri() -> str:
    """Return the redirect URI from lib.oauth so it stays in sync with the
    server's configured port.  Falls back to the constant in spotify_client if
    lib is not importable (e.g. during isolated testing)."""
    try:
        from lib import oauth as _oauth_lib  # noqa: PLC0415
        return _oauth_lib.get_redirect_uri("spotify")
    except Exception:
        return _DEFAULT_REDIRECT_URI


_REDIRECT_URI = _resolve_redirect_uri()

# Module-level client cache keyed by (client_id, client_secret).
# Persists across button presses within one process — no repeated OAuth overhead.
_client_cache: dict[tuple[str, str], SpotifyClient] = {}

# Short-lived playback state cache — avoids a GET /me/player on every button
# press (the legacy v1 code used a shared background-polled state for the same
# reason). Cache entries expire after _PB_TTL seconds.
_pb_cache: Optional[dict] = None
_pb_cache_ts: float = 0.0
_PB_TTL = 3.0  # seconds

_ART_IMG_DIR = _PLUGIN_DIR.parents[1] / "storage" / "spotify"
_ART_FILE = _ART_IMG_DIR / "_now_playing.jpg"
_ART_REL_PATH = "plugins/storage/spotify/_now_playing.jpg"
_STATE_FILE = _ART_IMG_DIR / "state.json"
_last_art_url: Optional[str] = None
# Sentinel stored in _last_spotify_face when the idle reset has already been
# sent for a slot.  Using a distinct object (not None or a tuple) lets us
# distinguish "confirmed idle" from "never polled yet", so the reset fires
# on the first idle poll even after a server restart.
_IDLE = object()
# Per-slot display state.  Values are either:
#   (art_url, label, time_left_str)  — last active state sent
#   _IDLE                            — idle reset already sent this session
#   (absent)                         — never polled (reset will fire on first idle poll)
_last_spotify_face: dict[tuple[str, int], Any] = {}
_rate_limited_until: float = 0.0


def _set_rate_limit_from_error(err: str) -> None:
    global _rate_limited_until
    msg = str(err or "")
    if "429" not in msg:
        return
    wait_s = 5.0
    m = re.search(r"Retry-After:\s*(\d+(?:\.\d+)?)", msg)
    if m:
        try:
            wait_s = max(1.0, float(m.group(1)))
        except (TypeError, ValueError):
            wait_s = 5.0
    _rate_limited_until = max(_rate_limited_until, time.monotonic() + wait_s)


def _is_rate_limited() -> bool:
    return time.monotonic() < _rate_limited_until


def _read_state_payload() -> dict:
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state_payload(pb: Optional[dict], error: str = "") -> None:
    try:
        _ART_IMG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": time.time(),
            "playback": pb if isinstance(pb, dict) else None,
            "error": str(error or ""),
        }
        _STATE_FILE.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _playback_from_state() -> Optional[dict]:
    payload = _read_state_payload()
    pb = payload.get("playback")
    return pb if isinstance(pb, dict) else None


def _refresh_playback_state(client: SpotifyClient, force: bool = False) -> Optional[dict]:
    """Single playback fetch path for the plugin.

    Uses in-memory cache and writes every successful fetch into
    plugins/storage/spotify/state.json so other functions can consume
    shared state without issuing their own API calls.
    """
    global _pb_cache, _pb_cache_ts

    now = time.monotonic()
    if not force:
        if _pb_cache is not None and (now - _pb_cache_ts) < _PB_TTL:
            return _pb_cache
        if _is_rate_limited():
            return _pb_cache if _pb_cache is not None else _playback_from_state()

    try:
        pb = client.get_playback()
        _pb_cache = pb
        _pb_cache_ts = now
        _write_state_payload(pb)
        return pb
    except Exception as exc:
        _set_rate_limit_from_error(str(exc))
        _write_state_payload(_pb_cache if isinstance(_pb_cache, dict) else _playback_from_state(), str(exc))
        return _pb_cache if _pb_cache is not None else _playback_from_state()


def _get_playback_cached(client: SpotifyClient) -> Optional[dict]:
    """Return playback state, reusing a recent cached result if available."""
    return _refresh_playback_state(client, force=False)


def _invalidate_pb_cache() -> None:
    global _pb_cache, _pb_cache_ts
    _pb_cache = None
    _pb_cache_ts = 0.0


def _pick_art_url(images: list) -> str:
    """Select the smallest album art image >= 80px tall."""
    if not images:
        return ""
    suitable = [i for i in images if (i.get("height") or 0) >= 80]
    if suitable:
        suitable.sort(key=lambda i: i.get("height", 0))
        return suitable[0]["url"]
    return images[0]["url"]


def _fetch_album_art(pb: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
    """Extract album art from playback state, download it, and return
    ``(relative_path, error)``."""
    global _last_art_url
    if not pb or not isinstance(pb, dict):
        return None, "no playback data"
    item = pb.get("item")
    if not isinstance(item, dict):
        return None, f"no item in playback (keys: {list(pb.keys())})"
    album = item.get("album")
    if not isinstance(album, dict):
        return None, "no album in item"
    images = album.get("images")
    if not images:
        return None, "no images in album"
    art_url = _pick_art_url(images)
    if not art_url:
        return None, "could not pick art URL"
    if art_url == _last_art_url and _ART_FILE.exists():
        return _ART_REL_PATH, None
    try:
        req = urllib.request.Request(art_url, headers={"User-Agent": "PyDeck/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
        if len(data) < 100:
            return None, f"downloaded data too small ({len(data)} bytes)"
        _ART_IMG_DIR.mkdir(parents=True, exist_ok=True)
        _ART_FILE.write_bytes(data)
        _last_art_url = art_url
        return _ART_REL_PATH, None
    except Exception as exc:
        return None, f"download failed: {exc}"


def _playback_art_url(pb: Optional[dict]) -> Optional[str]:
    """Album art URL from playback, or None if unavailable."""
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


def _build_track_label(pb: Optional[dict], mode: str = "song") -> str:
    """Build a display label from playback data based on *mode*.

    Modes: ``"song"``, ``"artist"``, ``"song_artist"``, ``"none"``.
    """
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


def _format_time_left(pb: Optional[dict]) -> str:
    """Format time remaining in the current track as ``-m:ss``.

    Returns an empty string when the playback state does not include
    duration/progress information (e.g. ads, podcasts without timecodes).
    """
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


def _build_text_display(pb: Optional[dict], config: Dict[str, Any]) -> Dict[str, Any]:
    """Build the text portion of a ``display_update`` from playback state.

    When *show_time_left* is enabled the function returns a ``text_labels``
    dict so the time remaining appears at the top and the track label (if any)
    at the bottom.  It also explicitly clears ``text`` so the scroll engine
    does not animate stale content alongside the multi-label render.

    Otherwise it falls back to a plain ``text`` string with marquee scroll
    enabled and clears ``text_labels`` so no leftover multi-label data from a
    previous mode lingers on the button.
    """
    mode = str(config.get("display_mode") or "none")
    show_time_left = bool(config.get("show_time_left", False))
    track_label = _build_track_label(pb, mode) if mode != "none" else ""

    if show_time_left:
        time_left = _format_time_left(pb)
        labels: Dict[str, str] = {}
        if time_left:
            labels["top"] = time_left
        if track_label:
            labels["bottom"] = track_label
        # Clear `text` explicitly — otherwise scroll_lib picks up the stale
        # single-label text and runs a marquee animation at the same time as
        # the multi-label render, causing visual jank.
        # Include scroll_speed so the bottom label animates when it overflows.
        if labels:
            return {"text_labels": labels, "text": "", "scroll_speed": 4}
        return {"text": "", "text_labels": None, "scroll_speed": 0}

    # Single-label path — supports marquee scrolling for long titles.
    # Clear `text_labels` so switching back from time-left mode is clean.
    if mode != "none":
        return {"text": track_label, "scroll_speed": 4, "text_labels": None}
    return {"text_labels": None}


# Number of preloaded second-by-second time-left frames pushed after each
# fresh Spotify API response when show_time_left is on.
_TIME_PRELOAD_SECONDS = 6


def _build_time_preloads(
    pb: Optional[dict], config: Dict[str, Any]
) -> list:
    """Return preload entries that tick the countdown every second.

    Each entry schedules a ``display_update`` at a future UNIX timestamp so the
    renderer applies it without waiting for the next Spotify poll.  This gives
    a smooth 1-second countdown using the same mechanism as the clock plugin,
    without extra API calls.

    Returns an empty list when the track is paused, time data is unavailable,
    or *show_time_left* is disabled.
    """
    if not bool(config.get("show_time_left", False)):
        return []
    if not pb or not isinstance(pb, dict) or not pb.get("is_playing"):
        return []
    item = pb.get("item")
    if not isinstance(item, dict):
        return []
    duration_ms = item.get("duration_ms")
    progress_ms = pb.get("progress_ms")
    if duration_ms is None or progress_ms is None:
        return []

    mode = str(config.get("display_mode") or "none")
    track_label = _build_track_label(pb, mode) if mode != "none" else ""
    now = time.time()

    out = []
    for i in range(1, _TIME_PRELOAD_SECONDS + 1):
        future_progress = int(progress_ms) + i * 1000
        remaining_ms = max(0, int(duration_ms) - future_progress)
        remaining_s = remaining_ms // 1000
        mins = remaining_s // 60
        secs = remaining_s % 60
        time_str = f"-{mins}:{secs:02d}"
        labels: Dict[str, str] = {"top": time_str}
        if track_label:
            labels["bottom"] = track_label
        out.append({
            "apply_at": now + i,
            "display_update": {"text_labels": labels, "text": "", "scroll_speed": 4},
        })
    return out


def _get_client(config: Dict[str, Any]) -> SpotifyClient:
    """Return a cached SpotifyClient, creating one if needed.

    Raises:
        SpotifyError: If credentials are missing.
    """
    cid = str(config.get("client_id") or "").strip()
    csec = str(config.get("client_secret") or "").strip()
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
            access_token=str(config.get("access_token") or "").strip(),
            refresh_token=str(config.get("refresh_token") or "").strip(),
            redirect_uri=_REDIRECT_URI,
        )
        _client_cache[key] = client
    else:
        # Pick up tokens written to credentials.json externally (e.g. after OAuth callback)
        if not client.access_token and config.get("access_token"):
            client.access_token = str(config["access_token"]).strip()
        if not client.refresh_token and config.get("refresh_token"):
            client.refresh_token = str(config["refresh_token"]).strip()
    return client


def _evict_client(config: Dict[str, Any]) -> None:
    """Remove a stale cache entry so the next press creates a fresh client."""
    key = (
        str(config.get("client_id") or "").strip(),
        str(config.get("client_secret") or "").strip(),
    )
    _client_cache.pop(key, None)


# ── Plugin functions ──────────────────────────────────────────────────────────

def poll_volume_display(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return the current volume as a label when 'Show Volume %' is enabled.

    Called by the generic display poller in start.py.
    """
    if not config.get("show_volume_label"):
        return {}
    try:
        pb = _playback_from_state()
        if pb is None:
            client = _get_client(config)
            pb = _refresh_playback_state(client, force=False)
        vol = (pb.get("device") or {}).get("volume_percent") if pb else None
        if vol is None:
            return {}
        return {"display_update": {"text": f"{vol}%"}}
    except Exception:
        return {}


def poll_display(config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch current playback state and return album art / track label if changed.

    Called by the generic display poller in start.py.
    Only returns ``display_update`` when something actually changed,
    so the poller doesn't needlessly write to disk or emit events.

    When *show_time_left* is enabled the function also schedules
    ``preload_display_updates`` for the next several seconds so the countdown
    ticks at 1-second resolution without extra Spotify API calls.
    """
    did = str(config.get("_device_id") or "")
    bid = config.get("_button_id")
    if not isinstance(bid, int):
        bid = 0
    key = (did, bid)
    _stored = _last_spotify_face.get(key)
    if isinstance(_stored, tuple):
        prev_art_sent, prev_label_sent, prev_time_left_sent = _stored
    else:
        prev_art_sent, prev_label_sent, prev_time_left_sent = None, None, None

    try:
        client = _get_client(config)
        pb = _refresh_playback_state(client, force=True)

        # ── Idle reset ────────────────────────────────────────────────────────
        # Spotify returns 204 (no active device) → _req converts that to {}.
        # Guard against both {} and None.
        # We use _IDLE as a sentinel so the reset fires on the *first* idle
        # poll, even after a server restart (when _last_spotify_face is empty
        # and prev_art_sent would otherwise be None, suppressing the reset).
        if not pb:
            if _last_spotify_face.get(key) is not _IDLE:
                _last_spotify_face[key] = _IDLE
                return {
                    "display_update": {
                        "image": "plugins/plugin/spotify/img/PlayPause.png",
                        "text": "",
                        "text_labels": None,
                    },
                    # Empty list signals the core to cancel any pending countdown
                    # preloads that were scheduled while the track was playing.
                    "preload_display_updates": [],
                }
            return {}

        art_path, _ = _fetch_album_art(pb)
        art_url = _playback_art_url(pb)

        display_update: Dict[str, Any] = {}

        if art_path and art_url != prev_art_sent:
            display_update["image"] = art_path

        show_time_left = bool(config.get("show_time_left", False))
        mode = str(config.get("display_mode") or "none")
        track_label = _build_track_label(pb, mode) if mode != "none" else ""
        time_left_str = _format_time_left(pb) if show_time_left else None

        text_changed = track_label != prev_label_sent
        time_changed = time_left_str != prev_time_left_sent

        if text_changed or time_changed:
            display_update.update(_build_text_display(pb, config))

        if display_update:
            new_art = art_url if "image" in display_update else prev_art_sent
            new_lbl = track_label if (text_changed or time_changed) else prev_label_sent
            new_tl  = time_left_str if (text_changed or time_changed) else prev_time_left_sent
            _last_spotify_face[key] = (new_art, new_lbl, new_tl)
            result: Dict[str, Any] = {"display_update": display_update}
            preloads = _build_time_preloads(pb, config)
            if preloads:
                result["preload_display_updates"] = preloads
            return result
        return {}
    except Exception as e:
        _set_rate_limit_from_error(str(e))
        return {}


def play_pause(config: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle Spotify play/pause.

    Args:
        config: Dict with Spotify credentials.

    Returns:
        Dict with success flag, action taken, and album art display_update.
    """
    try:
        client = _get_client(config)
    except (SpotifyError, Exception) as e:
        return {"success": False, "error": str(e)}

    pb = _refresh_playback_state(client, force=False)
    result: Dict[str, Any] = {"success": True}

    try:
        if pb and pb.get("is_playing"):
            client.pause()
            _invalidate_pb_cache()
            result.update(action="pause", is_playing=False)
        else:
            client.play()
            _invalidate_pb_cache()
            result.update(action="play", is_playing=True)
    except (SpotifyError, Exception) as e:
        _set_rate_limit_from_error(str(e))
        result.update(success=False, error=str(e))
        return result

    art_pb = _refresh_playback_state(client, force=True)
    art_path, art_err = _fetch_album_art(art_pb)
    if art_path:
        result["display_update"] = {"image": art_path}
    elif art_err:
        result["art_error"] = art_err

    text_fields = _build_text_display(art_pb, config)
    if text_fields:
        disp = result.setdefault("display_update", {})
        disp.update(text_fields)

    # When resuming playback with show_time_left enabled, seed the preload
    # queue immediately so the countdown ticks from the first second rather
    # than waiting up to 3 s for the next poll cycle.
    if result.get("action") == "play":
        preloads = _build_time_preloads(art_pb, config)
        if preloads:
            result["preload_display_updates"] = preloads

    return result


def next_track(config: Dict[str, Any]) -> Dict[str, Any]:
    """Skip to the next Spotify track.

    Args:
        config: Dict with Spotify credentials.

    Returns:
        Dict with success flag.
    """
    try:
        client = _get_client(config)
        client.next_track()
        return {"success": True, "action": "next"}
    except SpotifyError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_client(config)
        return {"success": False, "error": f"Unexpected error: {e}"}


def prev_track(config: Dict[str, Any]) -> Dict[str, Any]:
    """Go back to the previous Spotify track.

    Args:
        config: Dict with Spotify credentials.

    Returns:
        Dict with success flag.
    """
    try:
        client = _get_client(config)
        client.prev_track()
        return {"success": True, "action": "prev"}
    except SpotifyError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_client(config)
        return {"success": False, "error": f"Unexpected error: {e}"}


def volume_up(config: Dict[str, Any]) -> Dict[str, Any]:
    """Increase Spotify volume by a configurable step.

    Args:
        config: Dict with Spotify credentials and optional volume_step (default 10).

    Returns:
        Dict with success flag and new volume level.
    """
    try:
        client = _get_client(config)
        step = max(1, min(100, int(config.get("volume_step") or 10)))
        pb = _playback_from_state() or _refresh_playback_state(client, force=False)
        current = (pb.get("device") or {}).get("volume_percent", 50) if pb else 50
        new_vol = min(100, current + step)
        client.set_volume(new_vol)
        _invalidate_pb_cache()
        result: Dict[str, Any] = {"success": True, "action": "volume_up", "volume": new_vol}
        if config.get("show_volume_label"):
            result["display_update"] = {"text": f"{new_vol}%"}
        return result
    except SpotifyError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_client(config)
        return {"success": False, "error": f"Unexpected error: {e}"}


def volume_down(config: Dict[str, Any]) -> Dict[str, Any]:
    """Decrease Spotify volume by a configurable step.

    Args:
        config: Dict with Spotify credentials and optional volume_step (default 10).

    Returns:
        Dict with success flag and new volume level.
    """
    try:
        client = _get_client(config)
        step = max(1, min(100, int(config.get("volume_step") or 10)))
        pb = _playback_from_state() or _refresh_playback_state(client, force=False)
        current = (pb.get("device") or {}).get("volume_percent", 50) if pb else 50
        new_vol = max(0, current - step)
        client.set_volume(new_vol)
        _invalidate_pb_cache()
        result: Dict[str, Any] = {"success": True, "action": "volume_down", "volume": new_vol}
        if config.get("show_volume_label"):
            result["display_update"] = {"text": f"{new_vol}%"}
        return result
    except SpotifyError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_client(config)
        return {"success": False, "error": f"Unexpected error: {e}"}


def set_volume(config: Dict[str, Any]) -> Dict[str, Any]:
    """Set Spotify playback volume to a fixed level (0–100%).

    Config:
        volume_percent: target level (required).
        show_volume_label: when true, poller / press can show ``NN%`` on the button.
    """
    try:
        client = _get_client(config)
        raw = config.get("volume_percent")
        if raw is None or raw == "":
            return {"success": False, "error": "Configure Volume (%) for this button"}
        try:
            target = int(raw)
        except (TypeError, ValueError):
            return {"success": False, "error": "Volume (%) must be a whole number"}
        target = max(0, min(100, target))
        client.set_volume(target)
        _invalidate_pb_cache()
        result: Dict[str, Any] = {
            "success": True,
            "action": "set_volume",
            "volume": target,
        }
        if config.get("show_volume_label"):
            result["display_update"] = {"text": f"{target}%"}
        return result
    except SpotifyError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_client(config)
        return {"success": False, "error": f"Unexpected error: {e}"}


def toggle_shuffle(config: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle Spotify shuffle mode on/off.

    Args:
        config: Dict with Spotify credentials.

    Returns:
        Dict with success flag and new shuffle state.
    """
    try:
        client = _get_client(config)
        pb = _playback_from_state() or _refresh_playback_state(client, force=False)
        current_shuffle = pb.get("shuffle_state", False) if pb else False
        client.set_shuffle(not current_shuffle)
        _invalidate_pb_cache()
        return {"success": True, "action": "shuffle", "shuffle": not current_shuffle}
    except SpotifyError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_client(config)
        return {"success": False, "error": f"Unexpected error: {e}"}


def cycle_repeat(config: Dict[str, Any]) -> Dict[str, Any]:
    """Cycle Spotify repeat mode: off → context → track → off.

    Args:
        config: Dict with Spotify credentials.

    Returns:
        Dict with success flag and new repeat state.
    """
    try:
        client = _get_client(config)
        pb = _playback_from_state() or _refresh_playback_state(client, force=False)
        current = pb.get("repeat_state", "off") if pb else "off"
        next_state = {"off": "context", "context": "track", "track": "off"}.get(
            current, "off"
        )
        client.set_repeat(next_state)
        _invalidate_pb_cache()
        return {"success": True, "action": "repeat", "repeat": next_state}
    except SpotifyError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_client(config)
        return {"success": False, "error": f"Unexpected error: {e}"}
