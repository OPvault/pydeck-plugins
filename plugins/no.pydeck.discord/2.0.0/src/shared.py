"""PDK plugin no.pydeck.discord — shared utilities.

Owns the DiscordRPC connection cache, credential loading, and a short-lived
voice-state cache so several Discord buttons polling in the same process share
one IPC round trip.

Per-function handlers live under src/functions/<name>/handler.py
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

_SRC_DIR = Path(__file__).resolve().parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from discord_rpc import (  # noqa: E402
    DiscordRPC,
    DiscordRPCError,
    _DEFAULT_REDIRECT_URI,
)

PLUGIN_ID = "no.pydeck.discord"
_LEGACY_PLUGIN_ID = "discord"
_CREDS_PATH = Path.home() / ".config" / "pydeck" / "core" / "credentials.json"


def _resolve_redirect_uri() -> str:
    """Return the redirect URI from lib.oauth so it stays in sync with the
    server's configured port. Falls back to the constant in discord_rpc when
    lib is not importable (e.g. during isolated testing)."""
    try:
        from lib import oauth as _oauth_lib  # noqa: PLC0415

        return _oauth_lib.get_redirect_uri(PLUGIN_ID)
    except Exception:
        return _DEFAULT_REDIRECT_URI


_REDIRECT_URI = _resolve_redirect_uri()

# Cache keyed by (client_id, client_secret). The PDK runtime keeps this module
# alive for the lifetime of the process, so the authenticated IPC socket is
# reused across presses — no handshake per press.
_rpc_cache: dict[tuple[str, str], DiscordRPC] = {}

# Voice state shared by every Discord button in this process.
_voice_cache: Optional[Dict[str, bool]] = None
_voice_cache_ts: float = 0.0
_VOICE_TTL = 1.0

# Opening the IPC socket costs a Discord-side handshake that has been measured
# at 17-70s. Polling runs on the deck's render/request threads, so doing that
# inline freezes the whole grid until Discord answers. Connect on a background
# thread instead and report "no state yet" until the socket is live.
_warm_lock = threading.Lock()
_warming = False
_next_connect_attempt = 0.0
_CONNECT_COOLDOWN_S = 20.0


def _socket_is_live(rpc: DiscordRPC) -> bool:
    """True when the authenticated socket already exists (no I/O performed)."""
    return getattr(rpc, "_sock", None) is not None


def _start_connect_async(rpc: DiscordRPC) -> None:
    """Open the IPC connection off the caller's thread, at most one at a time."""
    global _warming, _next_connect_attempt
    with _warm_lock:
        if _warming or time.monotonic() < _next_connect_attempt:
            return
        _warming = True

    def _run() -> None:
        global _warming, _next_connect_attempt
        try:
            set_voice_state(rpc.get_voice_settings())
        except Exception:
            evict_rpc()
        finally:
            with _warm_lock:
                _warming = False
                # Cooldown keeps a failing connect from being retried on every
                # tick, which would stack handshake attempts against Discord.
                _next_connect_attempt = time.monotonic() + _CONNECT_COOLDOWN_S

    threading.Thread(target=_run, daemon=True).start()


def load_credentials(ctx: Any = None) -> Dict[str, Any]:
    """Return the plugin's credentials.

    ``ctx.credentials`` is populated on press and on the server's poll, but the
    hardware listener dispatches poll without credentials — so fall back to
    reading credentials.json directly. Both the RDNN key and the pre-RDNN slug
    are honoured, RDNN last so it wins.
    """
    merged: Dict[str, Any] = {}
    try:
        if _CREDS_PATH.is_file():
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


def _client_pair(ctx: Any) -> tuple[str, str]:
    creds = load_credentials(ctx)
    cid = str(creds.get("client_id") or "").strip()
    csec = str(creds.get("client_secret") or "").strip()
    return cid, csec


def get_rpc(ctx: Any) -> DiscordRPC:
    """Return a cached, authorized DiscordRPC instance.

    Raises DiscordRPCError when credentials are missing or the user has not
    completed the Authorize step yet.
    """
    cid, csec = _client_pair(ctx)
    if not cid or not csec:
        raise DiscordRPCError(
            "client_id and client_secret are required — "
            "configure them under Settings → Credentials"
        )

    key = (cid, csec)
    rpc = _rpc_cache.get(key)
    if rpc is None:
        rpc = DiscordRPC(cid, csec, redirect_uri=_REDIRECT_URI)
        _rpc_cache[key] = rpc

    if not rpc.is_authorized():
        raise DiscordRPCError(
            "Not authorized — open Settings → Credentials and click Authorize"
        )
    return rpc


def get_rpc_for_poll(ctx: Any) -> Optional[DiscordRPC]:
    """Return an authorized DiscordRPC, or None when polling cannot proceed.

    Never triggers the OAuth flow, so the poll loop can't block on user
    interaction. DiscordRPC loads saved tokens in __init__, so this succeeds as
    soon as a previous session authorized.
    """
    cid, csec = _client_pair(ctx)
    if not cid or not csec:
        return None
    key = (cid, csec)
    rpc = _rpc_cache.get(key)
    if rpc is not None:
        return rpc if rpc.is_authorized() else None
    rpc = DiscordRPC(cid, csec, redirect_uri=_REDIRECT_URI)
    if not rpc.is_authorized():
        return None
    _rpc_cache[key] = rpc
    return rpc


def evict_rpc(ctx: Any = None) -> None:
    """Drop cached connections so the next call reconnects from scratch.

    Closing the socket matters: the reader thread is a daemon holding it open,
    so merely dropping the reference leaks an ESTABLISHED connection to Discord
    for the life of the process. Those accumulate across reconnects and Discord
    answers the RPC handshake progressively more slowly as they pile up.
    """
    for rpc in list(_rpc_cache.values()):
        try:
            rpc._disconnect()
        except Exception:
            pass
    _rpc_cache.clear()
    invalidate_voice_state()


def set_voice_state(state: Optional[Dict[str, bool]]) -> Optional[Dict[str, bool]]:
    """Seed the shared cache from a value a press already confirmed."""
    global _voice_cache, _voice_cache_ts
    _voice_cache = dict(state) if state else None
    _voice_cache_ts = time.monotonic()
    return _voice_cache


def invalidate_voice_state() -> None:
    global _voice_cache, _voice_cache_ts
    _voice_cache = None
    _voice_cache_ts = 0.0


def poll_voice_state(ctx: Any) -> Optional[Dict[str, bool]]:
    """Return {"mute": bool, "deaf": bool}, or None when Discord is unreachable.

    Both Discord buttons poll on the same schedule; the TTL collapses that into
    a single GET_VOICE_SETTINGS per tick.
    """
    global _voice_cache, _voice_cache_ts
    now = time.monotonic()
    # A press handled in another process (the deck listener) never seeded this
    # process's cache, so the TTL would serve the pre-press value. The core sets
    # _force_refresh when it knows the state just changed underneath us.
    forced = bool((getattr(ctx, "config", None) or {}).get("_force_refresh"))
    if (
        not forced
        and _voice_cache is not None
        and (now - _voice_cache_ts) < _VOICE_TTL
    ):
        return _voice_cache

    rpc = get_rpc_for_poll(ctx)
    if rpc is None:
        return set_voice_state(None)

    if not _socket_is_live(rpc):
        # First poll after a restart: hand back "unknown" immediately and let
        # the connection come up in the background, rather than blocking the
        # caller (a deck render tick or an /api/deck/grid request) on it.
        _start_connect_async(rpc)
        return None

    try:
        return set_voice_state(rpc.get_voice_settings())
    except Exception:
        evict_rpc()
        return None


def status_hint(ctx: Any) -> str:
    """Short label explaining why no voice state is available.

    PDK presses have no return value, so the button face is the only place a
    setup problem can surface — the classic plugin relied on a toast.
    """
    cid, csec = _client_pair(ctx)
    if not cid or not csec:
        return "SETUP"
    if get_rpc_for_poll(ctx) is None:
        return "AUTH"
    return "OFF"
