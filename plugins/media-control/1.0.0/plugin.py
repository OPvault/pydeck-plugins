"""Media control plugin for PyDeck.

Supports Linux media control via:
- playerctl for transport (play/pause/next/previous)
- pactl or amixer for volume control
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple


def _run_cmd(cmd: List[str]) -> Tuple[bool, str, str, int]:
    """Run one command and capture result without raising."""

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


def _clamp_step(value: Any, default: int = 5) -> int:
    """Normalize volume step to a safe integer percentage."""

    try:
        step = int(value)
    except (TypeError, ValueError):
        step = default
    return max(1, min(50, step))


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

    ok, out, err, code = _run_cmd(cmd)
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
    ok, out, err, code = _run_cmd(cmd)
    return {
        "success": ok,
        "action": action,
        "backend": "xdotool",
        "command": cmd,
        "stdout": out,
        "stderr": err,
        "exit_code": code,
    }


def _volume_action(action: str, step_percent: int) -> Dict[str, Any]:
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

        ok, out, err, code = _run_cmd(cmd)
        return {
            "success": ok,
            "action": action,
            "backend": "pactl",
            "command": cmd,
            "stdout": out,
            "stderr": err,
            "exit_code": code,
        }

    amixer = shutil.which("amixer")
    if amixer:
        if action == "volume_up":
            cmd = [amixer, "set", "Master", f"{step_percent}%+"]
        elif action == "volume_down":
            cmd = [amixer, "set", "Master", f"{step_percent}%-"]
        else:
            cmd = [amixer, "set", "Master", "toggle"]

        ok, out, err, code = _run_cmd(cmd)
        return {
            "success": ok,
            "action": action,
            "backend": "amixer",
            "command": cmd,
            "stdout": out,
            "stderr": err,
            "exit_code": code,
        }

    fallback = _xdotool_media_key(action)
    if fallback.get("success"):
        return fallback

    return {
        "success": False,
        "action": action,
        "error": (
            "No supported volume backend found "
            "(pactl, amixer, or xdotool)."
        ),
        "details": fallback,
    }


def _dispatch_media(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Execute a media control action from button config.

    Expected config keys:
    - action: one of play_pause, play, pause, next_track, previous_track,
      volume_up, volume_down, mute_toggle
    - player: optional playerctl filter, e.g. 'spotify'
    - step_percent: volume change amount for volume actions
    """

    cfg = dict(config or {})
    action = str(cfg.get("action") or "play_pause").strip().lower()
    player = str(cfg.get("player") or "").strip()
    step_percent = _clamp_step(cfg.get("step_percent", 5))

    transport_map = {
        "play_pause": "play-pause",
        "play": "play",
        "pause": "pause",
        "next_track": "next",
        "previous_track": "previous",
    }

    if action in transport_map:
        mapped_action = transport_map[action]
        result = _playerctl_action(mapped_action, player)
        result["requested_action"] = action
        if player:
            result["player"] = player

        if result.get("success"):
            return result

        # Fallback for desktops/apps not exposing MPRIS correctly.
        fallback = _xdotool_media_key(mapped_action)
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

    if action in {"volume_up", "volume_down", "mute_toggle"}:
        result = _volume_action(action, step_percent)
        result["step_percent"] = step_percent
        return result

    return {
        "success": False,
        "action": action,
        "error": "Unsupported action.",
        "supported_actions": [
            "play_pause",
            "play",
            "pause",
            "next_track",
            "previous_track",
            "volume_up",
            "volume_down",
            "mute_toggle",
        ],
    }


def play_pause(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(config or {})
    cfg["action"] = "play_pause"
    return _dispatch_media(cfg)


def play(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(config or {})
    cfg["action"] = "play"
    return _dispatch_media(cfg)


def pause(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(config or {})
    cfg["action"] = "pause"
    return _dispatch_media(cfg)


def next_track(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(config or {})
    cfg["action"] = "next_track"
    return _dispatch_media(cfg)


def previous_track(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(config or {})
    cfg["action"] = "previous_track"
    return _dispatch_media(cfg)


def volume_up(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(config or {})
    cfg["action"] = "volume_up"
    return _dispatch_media(cfg)


def volume_down(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(config or {})
    cfg["action"] = "volume_down"
    return _dispatch_media(cfg)


def mute_toggle(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = dict(config or {})
    cfg["action"] = "mute_toggle"
    return _dispatch_media(cfg)


# Compatibility aliases for action configs that use title-cased names.
def Pause(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return pause(config)


def Play(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return play(config)
