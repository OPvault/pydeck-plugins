"""Discord plugin for PyDeck.

Toggles Discord microphone mute or deafen state via the Discord RPC protocol.
Requires a Discord application with the rpc, rpc.voice.read, and rpc.voice.write scopes.

First-time setup:
1. Create a Discord application at https://discord.com/developers/applications
2. Add http://localhost as a redirect URI
3. Enter the client_id and client_secret under Settings → API
4. On first press, Discord will show an authorization prompt — approve it
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


def _get_rpc(client_id: Any, client_secret: Any) -> DiscordRPC:
    """Return a cached, authorized DiscordRPC instance.

    Creates and authorizes a new instance on first call for a given
    (client_id, client_secret) pair. Subsequent calls reuse the existing
    persistent IPC socket connection.

    Raises:
        DiscordRPCError: If credentials are missing or authorization fails.
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
        rpc.authorize()

    return rpc


def _evict_rpc(client_id: Any, client_secret: Any) -> None:
    """Remove a stale RPC entry so the next press creates a fresh connection."""
    key = (str(client_id or "").strip(), str(client_secret or "").strip())
    _rpc_cache.pop(key, None)


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
