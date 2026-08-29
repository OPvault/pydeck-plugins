"""PDK shared module for no.pydeck.media-control.

Linux media transport and volume control, ported from the classic 1.0.0
plugin.  The backends are unchanged:

- **playerctl** drives transport (play / pause / next / previous) over MPRIS
- **pactl**, else **amixer**, drives the default sink's volume and mute
- **xdotool** ``XF86Audio*`` keys are the last-resort fallback

PDK adds a read side: the button faces show the player's real status, the
sink volume, and the mute state, so the helpers below also *query* the same
tools.  Every query goes through a short TTL cache — ``on_poll`` runs once
per process (server and listener both poll) and volume up/down poll the
same sink, so without it a handful of buttons would fork a subprocess each
every poll tick.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# How long a probe result stays fresh. Just under the fastest poll interval
# any function uses, so a tick still sees its own data but sibling buttons
# in the same process reuse it.
_CACHE_TTL = 0.9

_lock = threading.Lock()
_player_cache: Dict[str, Tuple[float, Tuple[str, str, str]]] = {}
_sink_cache: Optional[Tuple[float, Tuple[Optional[int], Optional[bool]]]] = None


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------


def run_cmd(cmd: List[str]) -> Tuple[bool, str, str, int]:
    """Run one command and capture its result without raising."""

    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        return (
            proc.returncode == 0,
            (proc.stdout or "").strip(),
            (proc.stderr or "").strip(),
            proc.returncode,
        )
    except OSError as exc:
        return False, "", str(exc), -1


def clamp_step(value: Any, default: int = 5) -> int:
    """Normalize a volume step to a safe integer percentage."""

    try:
        step = int(value)
    except (TypeError, ValueError):
        step = default
    return max(1, min(50, step))


def player_arg(ctx: Any) -> str:
    """The button's optional playerctl target, e.g. ``spotify``."""

    return str((getattr(ctx, "config", None) or {}).get("player") or "").strip()


def state_icon(ctx: Any, state_key: str, fallback: str) -> str:
    """Icon for *state_key*: the user's gallery pick if they made one.

    The core resolves ``display_states`` (manifest defaults overlaid with the
    user's per-state choice) into ``config['_state_images']``.  Falling back
    to the bundled asset keeps the button drawn when nothing was picked.
    """

    images = (getattr(ctx, "config", None) or {}).get("_state_images") or {}
    return str(images.get(state_key) or "").strip() or fallback


# ---------------------------------------------------------------------------
# Transport — playerctl, with an xdotool media-key fallback
# ---------------------------------------------------------------------------


def _playerctl_action(action: str, player: str) -> Dict[str, Any]:
    playerctl = shutil.which("playerctl")
    if not playerctl:
        return {
            "success": False,
            "action": action,
            "backend": "playerctl",
            "error": (
                "playerctl not found. Install it to use "
                "media transport actions."
            ),
        }

    cmd = [playerctl]
    if player:
        cmd.extend(["--player", player])
    else:
        # Try all available MPRIS players when no explicit target is set.
        cmd.append("--all-players")
    cmd.append(action)

    ok, out, err, code = run_cmd(cmd)
    return {
        "success": ok,
        "action": action,
        "backend": "playerctl",
        "command": cmd,
        "stdout": out,
        "stderr": err,
        "exit_code": code,
    }


def _xdotool_media_key(action: str) -> Dict[str, Any]:
    """Fallback to desktop media keys via xdotool."""

    xdotool = shutil.which("xdotool")
    if not xdotool:
        return {
            "success": False,
            "action": action,
            "backend": "xdotool",
            "error": "xdotool not found.",
        }

    key_map = {
        "play-pause": "XF86AudioPlay",
        "play": "XF86AudioPlay",
        "pause": "XF86AudioPause",
        "next": "XF86AudioNext",
        "previous": "XF86AudioPrev",
        "volume_up": "XF86AudioRaiseVolume",
        "volume_down": "XF86AudioLowerVolume",
        "mute_toggle": "XF86AudioMute",
    }
    key_name = key_map.get(action)
    if not key_name:
        return {
            "success": False,
            "action": action,
            "backend": "xdotool",
            "error": "Unsupported media key action.",
        }

    cmd = [xdotool, "key", key_name]
    ok, out, err, code = run_cmd(cmd)
    return {
        "success": ok,
        "action": action,
        "backend": "xdotool",
        "command": cmd,
        "stdout": out,
        "stderr": err,
        "exit_code": code,
    }


_TRANSPORT_MAP = {
    "play_pause": "play-pause",
    "play": "play",
    "pause": "pause",
    "next_track": "next",
    "previous_track": "previous",
}


def transport(action: str, player: str = "") -> Dict[str, Any]:
    """Run a transport *action* (``play_pause``, ``next_track``, ...)."""

    mapped = _TRANSPORT_MAP.get(action)
    if mapped is None:
        return {
            "success": False,
            "action": action,
            "error": "Unsupported action.",
            "supported_actions": sorted(_TRANSPORT_MAP),
        }

    invalidate_player(player)

    result = _playerctl_action(mapped, player)
    result["requested_action"] = action
    if player:
        result["player"] = player
    if result.get("success"):
        return result

    # Fallback for desktops/apps not exposing MPRIS correctly.
    fallback = _xdotool_media_key(mapped)
    fallback["requested_action"] = action
    if player:
        fallback["player"] = player
    if fallback.get("success"):
        fallback["fallback_from"] = "playerctl"
        return fallback

    return {
        "success": False,
        "action": action,
        "error": "Transport action failed for all supported backends.",
        "attempts": [result, fallback],
    }


# ---------------------------------------------------------------------------
# Volume — pactl, else amixer, else xdotool
# ---------------------------------------------------------------------------


def volume(action: str, step_percent: int) -> Dict[str, Any]:
    """Run ``volume_up``, ``volume_down`` or ``mute_toggle`` on the sink."""

    invalidate_sink()

    pactl = shutil.which("pactl")
    if pactl:
        if action == "volume_up":
            cmd = [
                pactl,
                "set-sink-volume",
                "@DEFAULT_SINK@",
                f"+{step_percent}%",
            ]
        elif action == "volume_down":
            cmd = [
                pactl,
                "set-sink-volume",
                "@DEFAULT_SINK@",
                f"-{step_percent}%",
            ]
        else:
            cmd = [pactl, "set-sink-mute", "@DEFAULT_SINK@", "toggle"]

        ok, out, err, code = run_cmd(cmd)
        return {
            "success": ok,
            "action": action,
            "backend": "pactl",
            "command": cmd,
            "stdout": out,
            "stderr": err,
            "exit_code": code,
            "step_percent": step_percent,
        }

    amixer = shutil.which("amixer")
    if amixer:
        if action == "volume_up":
            cmd = [amixer, "set", "Master", f"{step_percent}%+"]
        elif action == "volume_down":
            cmd = [amixer, "set", "Master", f"{step_percent}%-"]
        else:
            cmd = [amixer, "set", "Master", "toggle"]

        ok, out, err, code = run_cmd(cmd)
        return {
            "success": ok,
            "action": action,
            "backend": "amixer",
            "command": cmd,
            "stdout": out,
            "stderr": err,
            "exit_code": code,
            "step_percent": step_percent,
        }

    fallback = _xdotool_media_key(action)
    fallback["step_percent"] = step_percent
    if fallback.get("success"):
        return fallback

    return {
        "success": False,
        "action": action,
        "step_percent": step_percent,
        "error": (
            "No supported volume backend found "
            "(pactl, amixer, or xdotool)."
        ),
        "details": fallback,
    }


# ---------------------------------------------------------------------------
# Read side — what the button faces draw
# ---------------------------------------------------------------------------


def invalidate_player(player: str = "") -> None:
    """Drop cached player probes so the next poll re-reads playerctl."""

    with _lock:
        if player:
            _player_cache.pop(player, None)
        else:
            _player_cache.clear()


def invalidate_sink() -> None:
    """Drop the cached sink probe so the next poll re-reads the mixer."""

    global _sink_cache
    with _lock:
        _sink_cache = None


def _probe_player(player: str) -> Tuple[str, str, str]:
    """Return ``(status, title, artist)`` for *player*, blanks when idle.

    ``--all-players`` prints one line per player; the playing one wins so a
    single button follows whichever app is actually making sound.
    """

    playerctl = shutil.which("playerctl")
    if not playerctl:
        return "", "", ""

    cmd = [playerctl]
    cmd.extend(["--player", player] if player else ["--all-players"])
    cmd.extend(["metadata", "--format", "{{status}}\t{{title}}\t{{artist}}"])

    ok, out, _err, _code = run_cmd(cmd)
    if not ok or not out:
        return "", "", ""

    rows = []
    for line in out.splitlines():
        parts = (line.split("\t") + ["", "", ""])[:3]
        rows.append((parts[0].strip().lower(), parts[1].strip(), parts[2].strip()))
    for row in rows:
        if row[0] == "playing":
            return row
    return rows[0]


def probe_player(player: str = "") -> Tuple[str, str, str]:
    """Cached :func:`_probe_player`."""

    now = time.monotonic()
    with _lock:
        entry = _player_cache.get(player)
        if entry is not None and (now - entry[0]) < _CACHE_TTL:
            return entry[1]

    probed = _probe_player(player)
    with _lock:
        _player_cache[player] = (time.monotonic(), probed)
    return probed


def is_playing(player: str = "") -> bool:
    """True when the target player reports MPRIS status ``Playing``."""

    return probe_player(player)[0] == "playing"


def track_label(player: str, mode: str) -> str:
    """Format the now-playing line for *mode* (``song``/``artist``/...)."""

    if mode == "none":
        return ""

    _status, title, artist = probe_player(player)
    if mode == "artist":
        return artist
    if mode == "song_artist" and title and artist:
        return f"{title} - {artist}"
    return title


_PACTL_PERCENT_RE = re.compile(r"(\d+)%")
_AMIXER_PERCENT_RE = re.compile(r"\[(\d+)%\]")
_AMIXER_SWITCH_RE = re.compile(r"\[(on|off)\]")


def _probe_sink() -> Tuple[Optional[int], Optional[bool]]:
    """Return ``(volume_percent, muted)``; either is None if unreadable."""

    pactl = shutil.which("pactl")
    if pactl:
        vol: Optional[int] = None
        muted: Optional[bool] = None

        ok, out, _err, _code = run_cmd(
            [pactl, "get-sink-volume", "@DEFAULT_SINK@"],
        )
        if ok:
            match = _PACTL_PERCENT_RE.search(out)
            if match:
                vol = int(match.group(1))

        ok, out, _err, _code = run_cmd(
            [pactl, "get-sink-mute", "@DEFAULT_SINK@"],
        )
        if ok:
            muted = "yes" in out.lower()

        return vol, muted

    amixer = shutil.which("amixer")
    if amixer:
        ok, out, _err, _code = run_cmd([amixer, "get", "Master"])
        if not ok:
            return None, None
        vol_match = _AMIXER_PERCENT_RE.search(out)
        switch_match = _AMIXER_SWITCH_RE.search(out)
        return (
            int(vol_match.group(1)) if vol_match else None,
            switch_match.group(1) == "off" if switch_match else None,
        )

    return None, None


def probe_sink() -> Tuple[Optional[int], Optional[bool]]:
    """Cached :func:`_probe_sink`."""

    global _sink_cache
    now = time.monotonic()
    with _lock:
        if _sink_cache is not None and (now - _sink_cache[0]) < _CACHE_TTL:
            return _sink_cache[1]

    probed = _probe_sink()
    with _lock:
        _sink_cache = (time.monotonic(), probed)
    return probed


def volume_label(ctx: Any) -> str:
    """``"42%"`` when the button asked for it and the sink is readable."""

    if not ctx.config.get("show_volume_label", False):
        return ""
    vol, _muted = probe_sink()
    return f"{vol}%" if vol is not None else ""


def is_muted() -> Optional[bool]:
    """Mute state of the default sink, or None when unreadable."""

    return probe_sink()[1]
