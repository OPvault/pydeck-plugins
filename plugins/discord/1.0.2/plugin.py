"""Discord plugin for PyDeck.

Toggles Discord microphone mute or deafen state via the Discord RPC protocol.
Requires a Discord application with the rpc, rpc.voice.read, and rpc.voice.write scopes.

First-time setup:
1. Create a Discord application at https://discord.com/developers/applications
2. Add http://localhost:8686/oauth/discord/callback as a redirect URI
3. Enter the client_id and client_secret under Settings → API
4. Click Authorize in Settings → API to grant access
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

_PLUGIN_DIR = Path(__file__).parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from discord_rpc import DiscordRPC, DiscordRPCError  # noqa: E402

# Module-level RPC cache keyed by (client_id, client_secret).
# lib/button.py caches this plugin module via _module_cache, so this dict
# persists across button presses — no IPC handshake or OAuth overhead after
# the first authorized press.
_rpc_cache: dict[tuple[str, str], DiscordRPC] = {}

# Last known voice states for polling — None means "not yet polled".
_last_mute_state: dict[tuple[str, str], bool | None] = {}
_last_deafen_state: dict[tuple[str, str], bool | None] = {}


def _get_rpc(client_id: Any, client_secret: Any) -> DiscordRPC:
    """Return a cached, authorized DiscordRPC instance.

    Creates a new instance on first call for a given (client_id, client_secret)
    pair. Subsequent calls reuse the existing persistent IPC socket connection.
    Authorization must be completed via Settings → API before pressing a button.

    Raises:
        DiscordRPCError: If credentials are missing or not yet authorized.
    """
    cid = str(client_id or "").strip()
    csec = str(client_secret or "").strip()
    if not cid or not csec:
        raise DiscordRPCError(
            "client_id and client_secret are required — "
            "configure them under Settings → API"
        )

    key = (cid, csec)
    rpc = _rpc_cache.get(key)

    if rpc is None:
        rpc = DiscordRPC(cid, csec)
        _rpc_cache[key] = rpc

    if not rpc.is_authorized():
        raise DiscordRPCError(
            "Not authorized — open Settings → API and click Authorize"
        )

    return rpc


def _evict_rpc(client_id: Any, client_secret: Any) -> None:
    """Remove a stale RPC entry so the next press creates a fresh connection."""
    key = (str(client_id or "").strip(), str(client_secret or "").strip())
    _rpc_cache.pop(key, None)


def _get_rpc_for_poll(cid: str, csec: str):
    """Return an authorized DiscordRPC for polling, or None if not possible.

    Unlike _get_rpc, this never calls authorize() — it only succeeds when a
    valid saved token is already available, so the poll thread never blocks
    waiting for user interaction.
    """
    key = (cid, csec)
    rpc = _rpc_cache.get(key)
    if rpc is not None:
        return rpc if rpc.is_authorized() else None
    # No cached entry yet (e.g. server just started, button not pressed yet).
    # DiscordRPC.__init__ loads saved tokens from credentials.json automatically,
    # so is_authorized() will return True when a prior session's token exists.
    rpc = DiscordRPC(cid, csec)
    if not rpc.is_authorized():
        return None
    _rpc_cache[key] = rpc
    return rpc


def poll_mute_state(config: Dict[str, Any]) -> Dict[str, Any]:
    """Poll Discord mute state and update the button image if it changed.

    Called by the core's background poller every 10 s. Never triggers OAuth —
    returns {} immediately if no saved token is available.
    """
    cid = str(config.get("client_id") or "").strip()
    csec = str(config.get("client_secret") or "").strip()
    if not cid or not csec:
        return {}

    key = (cid, csec)
    rpc = _get_rpc_for_poll(cid, csec)
    if rpc is None:
        return {}

    try:
        voice = rpc.get_voice_settings()
        # Mirror toggle_deafen's related_states logic: deafening implies muted UI.
        effective_muted = voice["mute"] or voice["deaf"]
        if effective_muted == _last_mute_state.get(key):
            return {}
        _last_mute_state[key] = effective_muted
        image = (
            "plugins/plugin/discord/img/mute_1.png"
            if effective_muted
            else "plugins/plugin/discord/img/mute_0.png"
        )
        return {"display_update": {"image": image}}
    except Exception:
        return {}


def poll_deafen_state(config: Dict[str, Any]) -> Dict[str, Any]:
    """Poll Discord deafen state and update the button image if it changed.

    Called by the core's background poller every 10 s. Never triggers OAuth —
    returns {} immediately if no saved token is available.
    """
    cid = str(config.get("client_id") or "").strip()
    csec = str(config.get("client_secret") or "").strip()
    if not cid or not csec:
        return {}

    key = (cid, csec)
    rpc = _get_rpc_for_poll(cid, csec)
    if rpc is None:
        return {}

    try:
        voice = rpc.get_voice_settings()
        deafened = voice["deaf"]
        if deafened == _last_deafen_state.get(key):
            return {}
        _last_deafen_state[key] = deafened
        image = (
            "plugins/plugin/discord/img/deafen_1.png"
            if deafened
            else "plugins/plugin/discord/img/deafen_0.png"
        )
        return {"display_update": {"image": image}}
    except Exception:
        return {}


def toggle_mute(config: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle Discord microphone mute.

    Args:
        config: Dict with client_id, client_secret (from Settings → API)
                and optional label/color.

    Returns:
        Dict with success flag and current mute/deaf state.
    """
    try:
        rpc = _get_rpc(config.get("client_id"), config.get("client_secret"))
        state = rpc.toggle_mute()
        return {
            "success": True,
            "action": "mute",
            "muted": state["mute"],
            "deafened": state["deaf"],
            "state": "active" if state["mute"] else "default",
            "related_states": {
                "toggle_deafen": "active" if state["deaf"] else "default",
            },
        }
    except DiscordRPCError as e:
        _evict_rpc(config.get("client_id"), config.get("client_secret"))
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_rpc(config.get("client_id"), config.get("client_secret"))
        return {"success": False, "error": f"Unexpected error: {e}"}


def toggle_deafen(config: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle Discord deafen (mic + audio).

    Args:
        config: Dict with client_id, client_secret (from Settings → API)
                and optional label/color.

    Returns:
        Dict with success flag and current mute/deaf state.
    """
    try:
        rpc = _get_rpc(config.get("client_id"), config.get("client_secret"))
        state = rpc.toggle_deafen()
        return {
            "success": True,
            "action": "deafen",
            "muted": state["mute"],
            "deafened": state["deaf"],
            "state": "active" if state["deaf"] else "default",
            # Discord mutes you when deafening; RPC sometimes reports mute
            # before/after inconsistently — treat deafen as implying muted UI.
            "related_states": {
                "toggle_mute": (
                    "active" if (state["mute"] or state["deaf"]) else "default"
                ),
            },
        }
    except DiscordRPCError as e:
        _evict_rpc(config.get("client_id"), config.get("client_secret"))
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_rpc(config.get("client_id"), config.get("client_secret"))
        return {"success": False, "error": f"Unexpected error: {e}"}
