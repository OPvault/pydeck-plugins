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
        from lib import oauth as _oauth_lib
        return _oauth_lib.get_redirect_uri("spotify-pdk")
    except Exception:
        return _DEFAULT_REDIRECT_URI


_REDIRECT_URI = _resolve_redirect_uri()

_CREDS_PATH = Path.home() / ".config" / "pydeck" / "core" / "credentials.json"
_PLUGIN_NAME = "spotify-pdk"

_client_cache: dict[tuple[str, str], SpotifyClient] = {}

_pb_cache: Optional[dict] = None
_pb_cache_ts: float = 0.0
_PB_TTL = 3.0

_last_art_url: Optional[str] = None
_rate_limited_until: float = 0.0


def _load_credentials() -> Dict[str, Any]:
    """Load credentials from the shared credentials.json file."""
    if not _CREDS_PATH.exists():
        return {}
    try:
        data = json.loads(_CREDS_PATH.read_text(encoding="utf-8"))
        return data.get(_PLUGIN_NAME, {}) if isinstance(data, dict) else {}
    except Exception:
        return {}


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
    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": time.time(),
            "playback": pb if isinstance(pb, dict) else None,
            "error": str(error or ""),
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


def refresh_playback_state(
    client: SpotifyClient, storage_dir: Path, force: bool = False
) -> Optional[dict]:
    global _pb_cache, _pb_cache_ts

    now = time.monotonic()
    if not force:
        if _pb_cache is not None and (now - _pb_cache_ts) < _PB_TTL:
            return _pb_cache
        if _is_rate_limited():
            return _pb_cache if _pb_cache is not None else playback_from_state(storage_dir)

    try:
        pb = client.get_playback()
        _pb_cache = pb
        _pb_cache_ts = now
        _write_state_payload(storage_dir, pb)
        return pb
    except Exception as exc:
        _set_rate_limit_from_error(str(exc))
        fallback = _pb_cache if _pb_cache is not None else playback_from_state(storage_dir)
        _write_state_payload(storage_dir, fallback, str(exc))
        return fallback


def invalidate_pb_cache() -> None:
    global _pb_cache, _pb_cache_ts
    _pb_cache = None
    _pb_cache_ts = 0.0


def get_client(ctx: Any = None) -> SpotifyClient:
    """Return a cached SpotifyClient, loading credentials from disk.

    Credentials are read from ~/.config/pydeck/core/credentials.json so
    that both poll (no ctx.credentials) and press (has ctx.credentials)
    paths work reliably.
    """
    creds = _load_credentials()
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
            creds_key=_PLUGIN_NAME,
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
    rel_path = f"../../storage/{storage_dir.name}/_now_playing.jpg"

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
