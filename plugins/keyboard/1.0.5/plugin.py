"""Keyboard plugin for PyDeck.

Simulates keyboard input using xdotool on X11 when available, and falls back
to python-evdev/uinput for Wayland or when xdotool is unavailable.
The uinput path works on both X11 and Wayland without any display-server-
specific code.

Requirements:
    pip install evdev
    sudo apt install xdotool   # optional, for faster X11 input injection
    sudo usermod -aG input $USER   # then log out and back in
"""

from __future__ import annotations

import os
import select
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Set

try:
    import evdev
    from evdev import UInput, ecodes

    _EVDEV_AVAILABLE = True
except ImportError:
    _EVDEV_AVAILABLE = False

# Reverse map: evdev key code → friendly name (built once at import time)
_CODE_TO_NAME: Dict[int, str] = {}

if _EVDEV_AVAILABLE:
    _seen: Set[int] = set()
    for _name, _code in ecodes.ecodes.items():
        if (
            isinstance(_code, int)
            and _name.startswith("KEY_")
            and _code not in _seen
        ):
            _CODE_TO_NAME[_code] = _name[4:].lower()
            _seen.add(_code)
    del _seen

_MODIFIER_CODES: Set[int] = set()
_MODIFIER_NAMES: Dict[int, str] = {}

_XDOTOOL_AVAILABLE = shutil.which("xdotool") is not None
_HELD_HOTKEYS: Dict[str, str] = {}
_HELD_BACKENDS: Dict[str, str] = {}

if _EVDEV_AVAILABLE:
    _MODIFIER_NAMES = {
        ecodes.KEY_LEFTCTRL: "ctrl",
        ecodes.KEY_RIGHTCTRL: "ctrl",
        ecodes.KEY_LEFTALT: "alt",
        ecodes.KEY_RIGHTALT: "ralt",
        ecodes.KEY_LEFTSHIFT: "shift",
        ecodes.KEY_RIGHTSHIFT: "shift",
        ecodes.KEY_LEFTMETA: "super",
        ecodes.KEY_RIGHTMETA: "super",
    }
    _MODIFIER_CODES = set(_MODIFIER_NAMES.keys())

# Canonical modifier order when building combo strings
_MOD_ORDER = [
    ("ctrl",  {"KEY_LEFTCTRL", "KEY_RIGHTCTRL"}),
    ("alt",   {"KEY_LEFTALT"}),
    ("ralt",  {"KEY_RIGHTALT"}),
    ("shift", {"KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}),
    ("super", {"KEY_LEFTMETA", "KEY_RIGHTMETA"}),
]

# ---------------------------------------------------------------------------
# Key name → evdev ecodes constant name
# ---------------------------------------------------------------------------

_KEY_ALIASES: Dict[str, str] = {
    # Modifiers
    "ctrl": "KEY_LEFTCTRL",
    "control": "KEY_LEFTCTRL",
    "lctrl": "KEY_LEFTCTRL",
    "rctrl": "KEY_RIGHTCTRL",
    "alt": "KEY_LEFTALT",
    "lalt": "KEY_LEFTALT",
    "ralt": "KEY_RIGHTALT",
    "altgr": "KEY_RIGHTALT",
    "shift": "KEY_LEFTSHIFT",
    "lshift": "KEY_LEFTSHIFT",
    "rshift": "KEY_RIGHTSHIFT",
    "super": "KEY_LEFTMETA",
    "win": "KEY_LEFTMETA",
    "meta": "KEY_LEFTMETA",
    "cmd": "KEY_LEFTMETA",
    "hyper": "KEY_LEFTMETA",
    # Navigation
    "space": "KEY_SPACE",
    "enter": "KEY_ENTER",
    "return": "KEY_ENTER",
    "tab": "KEY_TAB",
    "backspace": "KEY_BACKSPACE",
    "delete": "KEY_DELETE",
    "del": "KEY_DELETE",
    "insert": "KEY_INSERT",
    "ins": "KEY_INSERT",
    "home": "KEY_HOME",
    "end": "KEY_END",
    "pageup": "KEY_PAGEUP",
    "pgup": "KEY_PAGEUP",
    "pagedown": "KEY_PAGEDOWN",
    "pgdown": "KEY_PAGEDOWN",
    "pgdn": "KEY_PAGEDOWN",
    "escape": "KEY_ESC",
    "esc": "KEY_ESC",
    # Lock keys
    "capslock": "KEY_CAPSLOCK",
    "numlock": "KEY_NUMLOCK",
    "scrolllock": "KEY_SCROLLLOCK",
    # System
    "printscreen": "KEY_SYSRQ",
    "prtsc": "KEY_SYSRQ",
    "sysrq": "KEY_SYSRQ",
    "pause": "KEY_PAUSE",
    # Arrow keys
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    # Media keys
    "mute": "KEY_MUTE",
    "volumeup": "KEY_VOLUMEUP",
    "volup": "KEY_VOLUMEUP",
    "volumedown": "KEY_VOLUMEDOWN",
    "voldown": "KEY_VOLUMEDOWN",
    "playpause": "KEY_PLAYPAUSE",
    "play": "KEY_PLAYPAUSE",
    "nextsong": "KEY_NEXTSONG",
    "next": "KEY_NEXTSONG",
    "previoussong": "KEY_PREVIOUSSONG",
    "prevsong": "KEY_PREVIOUSSONG",
    "prev": "KEY_PREVIOUSSONG",
    "stop": "KEY_STOPCD",
    "stopcd": "KEY_STOPCD",
    "brightnessup": "KEY_BRIGHTNESSUP",
    "brightnessdown": "KEY_BRIGHTNESSDOWN",
    # Numpad
    "num0": "KEY_KP0",
    "num1": "KEY_KP1",
    "num2": "KEY_KP2",
    "num3": "KEY_KP3",
    "num4": "KEY_KP4",
    "num5": "KEY_KP5",
    "num6": "KEY_KP6",
    "num7": "KEY_KP7",
    "num8": "KEY_KP8",
    "num9": "KEY_KP9",
    "numenter": "KEY_KPENTER",
    "numplus": "KEY_KPPLUS",
    "kpplus": "KEY_KPPLUS",
    "numminus": "KEY_KPMINUS",
    "kpminus": "KEY_KPMINUS",
    "nummultiply": "KEY_KPASTERISK",
    "kpmultiply": "KEY_KPASTERISK",
    "numdivide": "KEY_KPSLASH",
    "kpdivide": "KEY_KPSLASH",
    "numdot": "KEY_KPDOT",
    "kpdot": "KEY_KPDOT",
}

# Single printable character → evdev key constant name (US QWERTY, unshifted)
_CHAR_TO_KEY: Dict[str, str] = {
    "a": "KEY_A", "b": "KEY_B", "c": "KEY_C", "d": "KEY_D",
    "e": "KEY_E", "f": "KEY_F", "g": "KEY_G", "h": "KEY_H",
    "i": "KEY_I", "j": "KEY_J", "k": "KEY_K", "l": "KEY_L",
    "m": "KEY_M", "n": "KEY_N", "o": "KEY_O", "p": "KEY_P",
    "q": "KEY_Q", "r": "KEY_R", "s": "KEY_S", "t": "KEY_T",
    "u": "KEY_U", "v": "KEY_V", "w": "KEY_W", "x": "KEY_X",
    "y": "KEY_Y", "z": "KEY_Z",
    "0": "KEY_0", "1": "KEY_1", "2": "KEY_2", "3": "KEY_3",
    "4": "KEY_4", "5": "KEY_5", "6": "KEY_6", "7": "KEY_7",
    "8": "KEY_8", "9": "KEY_9",
    " ": "KEY_SPACE", "\t": "KEY_TAB", "\n": "KEY_ENTER",
    "-": "KEY_MINUS", "=": "KEY_EQUAL",
    "[": "KEY_LEFTBRACE", "]": "KEY_RIGHTBRACE",
    "\\": "KEY_BACKSLASH", ";": "KEY_SEMICOLON",
    "'": "KEY_APOSTROPHE", "`": "KEY_GRAVE",
    ",": "KEY_COMMA", ".": "KEY_DOT", "/": "KEY_SLASH",
}

# Characters that require Shift on a US layout, mapped to their base key
_SHIFT_CHARS: Dict[str, str] = {
    "A": "a", "B": "b", "C": "c", "D": "d", "E": "e",
    "F": "f", "G": "g", "H": "h", "I": "i", "J": "j",
    "K": "k", "L": "l", "M": "m", "N": "n", "O": "o",
    "P": "p", "Q": "q", "R": "r", "S": "s", "T": "t",
    "U": "u", "V": "v", "W": "w", "X": "x", "Y": "y",
    "Z": "z",
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\",
    ":": ";", '"': "'", "<": ",", ">": ".", "?": "/",
    "~": "`",
}

_X11_KEY_ALIASES: Dict[str, str] = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "lctrl": "ctrl",
    "rctrl": "ctrl",
    "alt": "alt",
    "lalt": "alt",
    "ralt": "ISO_Level3_Shift",
    "altgr": "ISO_Level3_Shift",
    "shift": "shift",
    "lshift": "shift",
    "rshift": "shift",
    "super": "super",
    "win": "super",
    "meta": "super",
    "cmd": "super",
    "hyper": "super",
    "space": "space",
    "enter": "Return",
    "return": "Return",
    "tab": "Tab",
    "backspace": "BackSpace",
    "delete": "Delete",
    "del": "Delete",
    "insert": "Insert",
    "ins": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "Page_Up",
    "pgup": "Page_Up",
    "pagedown": "Page_Down",
    "pgdown": "Page_Down",
    "pgdn": "Page_Down",
    "escape": "Escape",
    "esc": "Escape",
    "capslock": "Caps_Lock",
    "numlock": "Num_Lock",
    "scrolllock": "Scroll_Lock",
    "printscreen": "Print",
    "prtsc": "Print",
    "sysrq": "Print",
    "pause": "Pause",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "mute": "XF86AudioMute",
    "volumeup": "XF86AudioRaiseVolume",
    "volup": "XF86AudioRaiseVolume",
    "volumedown": "XF86AudioLowerVolume",
    "voldown": "XF86AudioLowerVolume",
    "playpause": "XF86AudioPlay",
    "play": "XF86AudioPlay",
    "nextsong": "XF86AudioNext",
    "next": "XF86AudioNext",
    "previoussong": "XF86AudioPrev",
    "prevsong": "XF86AudioPrev",
    "prev": "XF86AudioPrev",
    "stop": "XF86AudioStop",
    "stopcd": "XF86AudioStop",
    "brightnessup": "XF86MonBrightnessUp",
    "brightnessdown": "XF86MonBrightnessDown",
    "num0": "KP_0",
    "num1": "KP_1",
    "num2": "KP_2",
    "num3": "KP_3",
    "num4": "KP_4",
    "num5": "KP_5",
    "num6": "KP_6",
    "num7": "KP_7",
    "num8": "KP_8",
    "num9": "KP_9",
    "numenter": "KP_Enter",
    "numplus": "KP_Add",
    "kpplus": "KP_Add",
    "numminus": "KP_Subtract",
    "kpminus": "KP_Subtract",
    "nummultiply": "KP_Multiply",
    "kpmultiply": "KP_Multiply",
    "numdivide": "KP_Divide",
    "kpdivide": "KP_Divide",
    "numdot": "KP_Decimal",
    "kpdot": "KP_Decimal",
    "-": "minus",
    "=": "equal",
    "[": "bracketleft",
    "]": "bracketright",
    "\\": "backslash",
    ";": "semicolon",
    "'": "apostrophe",
    "`": "grave",
    ",": "comma",
    ".": "period",
    "/": "slash",
}


# ---------------------------------------------------------------------------
# Recording helpers
# ---------------------------------------------------------------------------

def _open_keyboards() -> List[Any]:
    """Return all evdev InputDevice objects that look like keyboards.

    Raises PermissionError if every accessible device was blocked by permissions.
    """
    devices = []
    permission_errors = 0
    total = 0
    for path in evdev.list_devices():
        total += 1
        try:
            dev = evdev.InputDevice(path)
            caps = dev.capabilities()
            keys = caps.get(ecodes.EV_KEY, [])
            if ecodes.KEY_A in keys and ecodes.KEY_Z in keys:
                devices.append(dev)
            else:
                dev.close()
        except PermissionError:
            permission_errors += 1
        except OSError:
            pass
    if not devices and permission_errors and permission_errors == total:
        raise PermissionError("/dev/input/* — permission denied for all devices")
    return devices


def _run_cmd(cmd: List[str]) -> Dict[str, Any]:
    """Run a command and capture stdout/stderr without raising."""
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        return {
            "success": proc.returncode == 0,
            "stdout": (proc.stdout or "").strip(),
            "stderr": (proc.stderr or "").strip(),
            "exit_code": proc.returncode,
        }
    except OSError as exc:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -1,
        }


def _session_is_wayland() -> bool:
    """Return True when the current desktop session is Wayland."""
    session_type = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if session_type:
        return session_type == "wayland"
    return bool(os.environ.get("WAYLAND_DISPLAY"))


def _session_is_x11() -> bool:
    """Return True when the current desktop session is X11."""
    session_type = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if session_type:
        return session_type == "x11"
    return bool(os.environ.get("DISPLAY")) and not bool(
        os.environ.get("WAYLAND_DISPLAY")
    )


def _preferred_backend() -> str:
    """Pick the fastest safe backend for the current session."""
    if _session_is_wayland():
        return "uinput"
    if _session_is_x11() and _XDOTOOL_AVAILABLE:
        return "xdotool"
    return "uinput"


def _button_event(config: Dict[str, Any]) -> str:
    return str(config.get("_button_event") or "press").strip().lower()


def _press_mode(config: Dict[str, Any]) -> str:
    return str(config.get("press_mode") or "press").strip().lower()


def _hold_state_key(config: Dict[str, Any]) -> str:
    button_id = config.get("_button_id")
    if button_id is not None:
        return f"id:{button_id}"
    hotkey = str(config.get("hotkey") or "").strip()
    return f"hotkey:{hotkey}"


def _resolve_xdotool_key(name: str) -> Optional[str]:
    """Resolve a shortcut part into an xdotool key name."""
    lower = name.strip().lower()

    if len(lower) == 1:
        if lower.isalnum():
            return lower
        return _X11_KEY_ALIASES.get(lower)

    if lower.startswith("f") and lower[1:].isdigit():
        num = int(lower[1:])
        if 1 <= num <= 24:
            return f"F{num}"

    return _X11_KEY_ALIASES.get(lower)


def _send_combo_xdotool(
    hotkey: str,
    repeat: int,
    delay_ms: int,
) -> Optional[Dict[str, Any]]:
    """Send a shortcut using xdotool on X11."""
    xdotool = shutil.which("xdotool")
    if not xdotool:
        return None

    parts = [p.strip() for p in hotkey.split("+") if p.strip()]
    key_parts: List[str] = []
    for part in parts:
        key_name = _resolve_xdotool_key(part)
        if key_name is None:
            return {
                "success": False,
                "backend": "xdotool",
                "hotkey": hotkey,
                "repeat": repeat,
                "error": f"Unknown key in shortcut: {hotkey!r}",
            }
        key_parts.append(key_name)

    for i in range(repeat):
        cmd = [xdotool, "key", "--clearmodifiers", *key_parts]
        run_result = _run_cmd(cmd)
        if not run_result["success"]:
            return {
                "success": False,
                "backend": "xdotool",
                "hotkey": hotkey,
                "repeat": repeat,
                "command": cmd,
                **run_result,
            }
        if i < repeat - 1 and delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

    return {
        "success": True,
        "backend": "xdotool",
        "hotkey": hotkey,
        "repeat": repeat,
    }


def _send_combo_xdotool_state(hotkey: str, pressed: bool) -> Optional[Dict[str, Any]]:
    """Hold or release a shortcut using xdotool on X11."""
    xdotool = shutil.which("xdotool")
    if not xdotool:
        return None

    parts = [p.strip() for p in hotkey.split("+") if p.strip()]
    key_parts: List[str] = []
    for part in parts:
        key_name = _resolve_xdotool_key(part)
        if key_name is None:
            return {
                "success": False,
                "backend": "xdotool",
                "hotkey": hotkey,
                "error": f"Unknown key in shortcut: {hotkey!r}",
            }
        key_parts.append(key_name)

    ordered_keys = key_parts if pressed else list(reversed(key_parts))
    command = "keydown" if pressed else "keyup"

    for key_name in ordered_keys:
        cmd = [xdotool, command, key_name]
        run_result = _run_cmd(cmd)
        if not run_result["success"]:
            return {
                "success": False,
                "backend": "xdotool",
                "hotkey": hotkey,
                "state": "down" if pressed else "up",
                "command": cmd,
                **run_result,
            }

    return {
        "success": True,
        "backend": "xdotool",
        "hotkey": hotkey,
        "state": "down" if pressed else "up",
    }


def _type_text_xdotool(text: str, delay_ms: int) -> Optional[Dict[str, Any]]:
    """Type text using xdotool on X11."""
    xdotool = shutil.which("xdotool")
    if not xdotool:
        return None

    # Keep a small delay floor on X11 so long strings stay responsive.
    effective_delay = max(0, min(5, int(delay_ms)))
    cmd = [xdotool, "type", "--clearmodifiers"]
    if effective_delay > 0:
        cmd.extend(["--delay", str(effective_delay)])
    cmd.extend(["--", text])
    run_result = _run_cmd(cmd)
    if not run_result["success"]:
        return {
            "success": False,
            "backend": "xdotool",
            "text": text,
            "command": cmd,
            **run_result,
        }
    return {
        "success": True,
        "backend": "xdotool",
        "text": text,
        "length": len(text),
        "command": cmd,
    }


def _build_combo_string(held_mods: Set[int], key_code: int) -> str:
    """Format held modifier codes + a final key code into 'ctrl+shift+a'."""
    parts: List[str] = []
    for label, ecode_names in _MOD_ORDER:
        codes_for_mod = {
            ecodes.ecodes[n]
            for n in ecode_names
            if n in ecodes.ecodes
        }
        if held_mods & codes_for_mod:
            parts.append(label)
    # Final key: use our friendly alias if one exists, else raw code name
    key_name = _CODE_TO_NAME.get(key_code, f"key{key_code}")
    parts.append(key_name)
    return "+".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_key_code(name: str) -> Optional[int]:
    """Resolve a key name to an evdev integer key code, or None if unknown."""
    lower = name.strip().lower()

    ecode_name = _KEY_ALIASES.get(lower)

    if ecode_name is None:
        # Function keys: f1 – f24
        if lower.startswith("f") and lower[1:].isdigit():
            num = int(lower[1:])
            if 1 <= num <= 24:
                ecode_name = f"KEY_F{num}"

    if ecode_name is None and len(lower) == 1:
        ecode_name = _CHAR_TO_KEY.get(lower)

    # Fall back: treat the raw name as an ecodes constant (e.g. "KEY_LEFTCTRL")
    if ecode_name is None:
        ecode_name = lower.upper()

    if not _EVDEV_AVAILABLE:
        return None

    code = ecodes.ecodes.get(ecode_name)
    if code is None:
        code = ecodes.ecodes.get(f"KEY_{ecode_name.upper()}")
    return code


def _parse_hotkey(hotkey: str) -> Optional[List[int]]:
    """Split 'ctrl+alt+delete' into a list of evdev key codes."""
    parts = [p.strip() for p in hotkey.split("+") if p.strip()]
    if not parts:
        return None
    codes: List[int] = []
    for part in parts:
        code = _resolve_key_code(part)
        if code is None:
            return None
        codes.append(code)
    return codes


def _send_combo(codes: List[int]) -> None:
    """Create a uinput device, hold all keys down then release them."""
    capabilities = {ecodes.EV_KEY: list(set(codes))}
    with UInput(capabilities, name="pydeck-keyboard") as ui:
        # Brief settle: let the OS register the virtual device before events.
        time.sleep(0.05)
        for code in codes:
            ui.write(ecodes.EV_KEY, code, 1)
        ui.syn()
        time.sleep(0.03)
        for code in reversed(codes):
            ui.write(ecodes.EV_KEY, code, 0)
        ui.syn()
        time.sleep(0.02)


def _send_combo_state(codes: List[int], pressed: bool) -> None:
    """Create a uinput device and emit either key-down or key-up events."""
    capabilities = {ecodes.EV_KEY: list(set(codes))}
    with UInput(capabilities, name="pydeck-keyboard") as ui:
        time.sleep(0.05)
        ordered_codes = codes if pressed else list(reversed(codes))
        value = 1 if pressed else 0
        for code in ordered_codes:
            ui.write(ecodes.EV_KEY, code, value)
        ui.syn()
        time.sleep(0.02)


def _collect_text_capabilities(text: str) -> List[int]:
    """Return all evdev key codes needed to type the given text."""
    codes: set[int] = set()
    shift_code = ecodes.ecodes.get("KEY_LEFTSHIFT")
    if shift_code is not None:
        codes.add(shift_code)
    for char in text:
        base = _SHIFT_CHARS.get(char, char)
        key_name = _CHAR_TO_KEY.get(base)
        if key_name:
            code = ecodes.ecodes.get(key_name)
            if code is not None:
                codes.add(code)
    return list(codes)


def _write_char(ui: Any, char: str) -> None:
    """Emit key-down / key-up events for a single character."""
    need_shift = char in _SHIFT_CHARS
    base = _SHIFT_CHARS.get(char, char)
    key_name = _CHAR_TO_KEY.get(base)
    if not key_name:
        return
    code = ecodes.ecodes.get(key_name)
    if code is None:
        return
    shift = ecodes.ecodes.get("KEY_LEFTSHIFT")
    if need_shift and shift is not None:
        ui.write(ecodes.EV_KEY, shift, 1)
    ui.write(ecodes.EV_KEY, code, 1)
    ui.syn()
    ui.write(ecodes.EV_KEY, code, 0)
    if need_shift and shift is not None:
        ui.write(ecodes.EV_KEY, shift, 0)
    ui.syn()


# ---------------------------------------------------------------------------
# Plugin functions
# ---------------------------------------------------------------------------

def press_key(config: Dict[str, Any]) -> Dict[str, Any]:
    """Press a key or key combination (e.g. ctrl+c, super+l, F5)."""
    cfg = dict(config or {})
    hotkey = str(cfg.get("hotkey") or "").strip()
    if not hotkey:
        return {"success": False, "error": "No key or shortcut specified."}

    mode = _press_mode(cfg)
    event = _button_event(cfg)
    hold_key = _hold_state_key(cfg)

    if mode == "hold":
        stored_hotkey = _HELD_HOTKEYS.get(hold_key, hotkey)
        stored_backend = _HELD_BACKENDS.get(hold_key, _preferred_backend())

        if event == "release":
            hotkey = stored_hotkey
            backend = stored_backend
            if not hotkey:
                return {"success": False, "error": "No key or shortcut specified."}

            if backend == "xdotool":
                xdotool_result = _send_combo_xdotool_state(hotkey, False)
                if xdotool_result is not None:
                    _HELD_HOTKEYS.pop(hold_key, None)
                    _HELD_BACKENDS.pop(hold_key, None)
                    return xdotool_result
            else:
                codes = _parse_hotkey(hotkey)
                if codes is None:
                    return {
                        "success": False,
                        "error": f"Unknown key in shortcut: {hotkey!r}",
                    }

                try:
                    if not _EVDEV_AVAILABLE:
                        return {
                            "success": False,
                            "error": "evdev is not installed. Run: pip install evdev",
                        }

                    _send_combo_state(codes, False)
                except PermissionError:
                    return {
                        "success": False,
                        "error": (
                            "Permission denied accessing /dev/uinput. "
                            "Add your user to the 'input' group: "
                            "sudo usermod -aG input $USER  (then log out and back in)."
                        ),
                    }
                except Exception as exc:
                    return {"success": False, "error": str(exc)}

                _HELD_HOTKEYS.pop(hold_key, None)
                _HELD_BACKENDS.pop(hold_key, None)
                return {
                    "success": True,
                    "hotkey": hotkey,
                    "mode": mode,
                    "state": "up",
                }

            return {
                "success": False,
                "error": "xdotool is not available for release.",
            }

        backend = _preferred_backend()
        if backend == "xdotool":
            xdotool_result = _send_combo_xdotool_state(hotkey, True)
            if xdotool_result is not None:
                if xdotool_result.get("success") or not _EVDEV_AVAILABLE:
                    _HELD_HOTKEYS[hold_key] = hotkey
                    _HELD_BACKENDS[hold_key] = backend
                    return xdotool_result
            backend = "uinput"

        codes = _parse_hotkey(hotkey)
        if codes is None:
            return {
                "success": False,
                "error": f"Unknown key in shortcut: {hotkey!r}",
            }

        try:
            if not _EVDEV_AVAILABLE:
                return {
                    "success": False,
                    "error": "evdev is not installed. Run: pip install evdev",
                }

            _send_combo_state(codes, True)
        except PermissionError:
            return {
                "success": False,
                "error": (
                    "Permission denied accessing /dev/uinput. "
                    "Add your user to the 'input' group: "
                    "sudo usermod -aG input $USER  (then log out and back in)."
                ),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        _HELD_HOTKEYS[hold_key] = hotkey
        _HELD_BACKENDS[hold_key] = backend
        return {
            "success": True,
            "hotkey": hotkey,
            "mode": mode,
            "state": "down",
        }

    if event == "release":
        return {"success": True, "ignored": True, "mode": mode, "state": "up"}

    try:
        repeat = max(1, min(100, int(cfg.get("repeat") or 1)))
    except (TypeError, ValueError):
        repeat = 1

    try:
        delay_ms = max(0, min(5000, int(cfg.get("delay_ms") or 50)))
    except (TypeError, ValueError):
        delay_ms = 50

    backend = _preferred_backend()
    if backend == "xdotool":
        xdotool_result = _send_combo_xdotool(hotkey, repeat, delay_ms)
        if xdotool_result is not None:
            if xdotool_result.get("success") or not _EVDEV_AVAILABLE:
                return xdotool_result

    codes = _parse_hotkey(hotkey)
    if codes is None:
        return {
            "success": False,
            "error": f"Unknown key in shortcut: {hotkey!r}",
        }

    try:
        if not _EVDEV_AVAILABLE:
            return {
                "success": False,
                "error": "evdev is not installed. Run: pip install evdev",
            }

        for i in range(repeat):
            _send_combo(codes)
            if i < repeat - 1 and delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
    except PermissionError:
        return {
            "success": False,
            "error": (
                "Permission denied accessing /dev/uinput. "
                "Add your user to the 'input' group: "
                "sudo usermod -aG input $USER  (then log out and back in)."
            ),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "hotkey": hotkey,
        "repeat": repeat,
        "mode": mode,
        "state": "tap",
    }


def type_text(config: Dict[str, Any]) -> Dict[str, Any]:
    """Type a string of text character by character (US keyboard layout)."""
    cfg = dict(config or {})
    text = str(cfg.get("text") or "")
    if not text:
        return {"success": False, "error": "No text specified."}

    try:
        delay_ms = max(0, min(1000, int(cfg.get("delay_ms") or 30)))
    except (TypeError, ValueError):
        delay_ms = 30

    backend = _preferred_backend()
    if backend == "xdotool":
        xdotool_result = _type_text_xdotool(text, delay_ms)
        if xdotool_result is not None:
            if xdotool_result.get("success") or not _EVDEV_AVAILABLE:
                return xdotool_result

    if not _EVDEV_AVAILABLE:
        return {
            "success": False,
            "error": "evdev is not installed. Run: pip install evdev",
        }

    capabilities = _collect_text_capabilities(text)

    try:
        with UInput({ecodes.EV_KEY: capabilities}, name="pydeck-keyboard") as ui:
            time.sleep(0.05)
            for i, char in enumerate(text):
                _write_char(ui, char)
                if i < len(text) - 1 and delay_ms > 0:
                    time.sleep(delay_ms / 1000.0)
    except PermissionError:
        return {
            "success": False,
            "error": (
                "Permission denied accessing /dev/uinput. "
                "Add your user to the 'input' group: "
                "sudo usermod -aG input $USER  (then log out and back in)."
            ),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    return {
        "success": True,
        "text": text,
        "length": len(text),
    }


def api_record(config: Dict[str, Any]) -> Dict[str, Any]:
    """Capture the next key combo pressed on any keyboard.

    Blocks until a non-modifier key is pressed (or timeout expires).
    Modifier-only presses (Ctrl, Alt, Shift, Super alone) are ignored so
    that e.g. Shift+A is captured as the full combo, not just "shift".

    Exposed at GET /api/plugins/keyboard/api/record
    Optional config key: timeout (seconds, default 10, max 30)
    Returns: {"success": true, "hotkey": "ctrl+c"}
    """
    if not _EVDEV_AVAILABLE:
        return {"success": False, "error": "evdev is not installed. Run: pip install evdev"}

    try:
        timeout = float(config.get("timeout") or 10)
    except (TypeError, ValueError):
        timeout = 10.0
    timeout = max(1.0, min(30.0, timeout))

    try:
        devices = _open_keyboards()
    except PermissionError:
        return {
            "success": False,
            "error": (
                "Permission denied reading /dev/input/*. "
                "Add your user to the 'input' group: sudo usermod -aG input $USER"
            ),
        }

    if not devices:
        return {
            "success": False,
            "error": "No keyboard devices found under /dev/input/. Check group membership.",
        }

    held_mods: Set[int] = set()
    deadline = time.monotonic() + timeout

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {"success": False, "error": "Timeout: no key combo was pressed."}

            readable, _, _ = select.select(devices, [], [], remaining)
            if not readable:
                return {"success": False, "error": "Timeout: no key combo was pressed."}

            for dev in readable:
                try:
                    events = dev.read()
                except OSError:
                    continue
                for event in events:
                    if event.type != ecodes.EV_KEY:
                        continue
                    code: int = event.code
                    value: int = event.value  # 1=down, 0=up, 2=repeat
                    if value == 1:  # key down
                        if code in _MODIFIER_CODES:
                            held_mods.add(code)
                        else:
                            return {
                                "success": True,
                                "hotkey": _build_combo_string(held_mods, code),
                            }
                    elif value == 0:  # key up
                        held_mods.discard(code)
    except PermissionError:
        return {
            "success": False,
            "error": (
                "Permission denied reading input device. "
                "Add your user to the 'input' group: sudo usermod -aG input $USER"
            ),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    finally:
        for dev in devices:
            try:
                dev.close()
            except OSError:
                pass
