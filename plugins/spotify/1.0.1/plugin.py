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
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

_PLUGIN_DIR = Path(__file__).parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from spotify_client import SpotifyClient, SpotifyError  # noqa: E402

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
_last_art_url: Optional[str] = None
# Last album-art URL + track label applied per deck slot (poller passes
# _device_id / _button_id). Globals would make only the first deck update.
_last_spotify_face: dict[tuple[str, int], tuple[Optional[str], Optional[str]]] = {}


def _get_playback_cached(client: SpotifyClient) -> Optional[dict]:
    """Return playback state, reusing a recent cached result if available."""
    global _pb_cache, _pb_cache_ts
    now = time.monotonic()
    if _pb_cache is not None and (now - _pb_cache_ts) < _PB_TTL:
        return _pb_cache
    pb = client.get_playback()
    _pb_cache = pb
    _pb_cache_ts = now
    return pb


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
        client = _get_client(config)
        pb = _get_playback_cached(client)
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
    """
    did = str(config.get("_device_id") or "")
    bid = config.get("_button_id")
    if not isinstance(bid, int):
        bid = 0
    key = (did, bid)
    prev_art_sent, prev_label_sent = _last_spotify_face.get(key, (None, None))

    try:
        client = _get_client(config)
        pb = client.get_playback()
        art_path, _ = _fetch_album_art(pb)
        art_url = _playback_art_url(pb)

        display_update: Dict[str, Any] = {}

        if art_path and art_url != prev_art_sent:
            display_update["image"] = art_path

        mode = str(config.get("display_mode") or "none")
        track_label = _build_track_label(pb, mode)
        if track_label != prev_label_sent:
            display_update["text"] = track_label or ""
            display_update["scroll_speed"] = 4

        if display_update:
            new_art = prev_art_sent
            new_lbl = prev_label_sent
            if "image" in display_update:
                new_art = art_url
            if "text" in display_update:
                new_lbl = track_label
            _last_spotify_face[key] = (new_art, new_lbl)
            return {"display_update": display_update}
        return {}
    except Exception:
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

    pb = _get_playback_cached(client)
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
        result.update(success=False, error=str(e))

    art_pb = pb if (pb and pb.get("item")) else client.get_playback()
    art_path, art_err = _fetch_album_art(art_pb)
    if art_path:
        result["display_update"] = {"image": art_path}
    elif art_err:
        result["art_error"] = art_err

    mode = str(config.get("display_mode") or "none")
    track_label = _build_track_label(art_pb, mode)
    if track_label:
        disp = result.setdefault("display_update", {})
        disp["text"] = track_label
        disp["scroll_speed"] = 4

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
        pb = _get_playback_cached(client)
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
        pb = _get_playback_cached(client)
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
        pb = _get_playback_cached(client)
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
        pb = _get_playback_cached(client)
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
