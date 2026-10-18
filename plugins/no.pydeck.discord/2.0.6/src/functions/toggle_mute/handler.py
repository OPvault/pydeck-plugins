"""Toggle Mute — toggle the Discord microphone via the local RPC socket."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent

# Both button handlers must share ONE shared.py instance: it owns the RPC
# connection cache and the voice-state cache. Executing the module per handler
# gave each its own caches, so every button opened a second Discord IPC socket
# and re-ran AUTHENTICATE -- which Discord stalls on for ~27s -- and the
# 1s voice cache never deduplicated the polls it exists to deduplicate.
# The name is plugin-scoped so a different plugin's shared.py can't collide.
_SHARED_NAME = "no_pydeck_discord_shared"
_shared = sys.modules.get(_SHARED_NAME)
if _shared is None:
    _spec = importlib.util.spec_from_file_location(_SHARED_NAME, str(_ROOT / "shared.py"))
    _shared = importlib.util.module_from_spec(_spec)
    sys.modules[_SHARED_NAME] = _shared
    _spec.loader.exec_module(_shared)

get_rpc = _shared.get_rpc
evict_rpc = _shared.evict_rpc
poll_voice_state = _shared.poll_voice_state
set_voice_state = _shared.set_voice_state
status_hint = _shared.status_hint

_ICON_LIVE = "assets/icons/mic.png"
_ICON_MUTED = "assets/icons/mic_off.png"


def _icon(ctx: Any, state_key: str, fallback: str) -> str:
    """Icon for *state_key*: the user's gallery pick if they made one.

    The core resolves display_states (manifest defaults overlaid with whatever
    the user chose per state) into config['_state_images']. Falling back to the
    bundled asset keeps the button working when nothing has been picked.
    """
    images = (getattr(ctx, "config", None) or {}).get("_state_images") or {}
    chosen = str(images.get(state_key) or "").strip()
    return chosen or fallback


def _apply(ctx: Any, voice: dict | None) -> None:
    """Paint the face from a voice state, or show why there isn't one."""
    if voice is None:
        ctx.state.icon_src = _icon(ctx, "default", _ICON_LIVE)
        ctx.state.face_class = "face-offline"
        ctx.state.hint = status_hint(ctx)
        ctx.state._template = "toggle_mute-hint"
        return

    # Deafening implies muted, so the mic button reflects either state — this
    # matches what Discord itself shows.
    muted = bool(voice.get("mute")) or bool(voice.get("deaf"))
    ctx.state.icon_src = (
        _icon(ctx, "active", _ICON_MUTED) if muted
        else _icon(ctx, "default", _ICON_LIVE)
    )
    ctx.state.face_class = "face-active" if muted else ""
    ctx.state.hint = ""
    ctx.state._template = "toggle_mute"


def on_load(ctx: Any) -> None:
    ctx.state._template = "toggle_mute"
    ctx.state.icon_src = _icon(ctx, "default", _ICON_LIVE)
    ctx.state.face_class = ""
    ctx.state.hint = ""


def on_poll(ctx: Any, interval: int = 5000) -> None:
    _apply(ctx, poll_voice_state(ctx))


def on_press(ctx: Any) -> None:
    try:
        state = get_rpc(ctx).toggle_mute()
    except Exception:
        evict_rpc()
        _apply(ctx, None)
        return
    _apply(ctx, set_voice_state(state))
