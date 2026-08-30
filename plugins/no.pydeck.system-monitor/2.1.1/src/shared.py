"""Shared utilities for PDK System Monitor.

Two halves.  The lower one reads the machine -- CPU, RAM, GPU, disk, network
and battery -- out of ``/proc`` and ``/sys`` first and off a command-line tool
only when the kernel will not answer, so the plugin needs no third-party
package.  The upper one turns a reading into a button face.

Every face is the same four things: a header, one big value, a sub line and a
bar.  A *theme* supplies the palette and the type; a *layout* supplies the
geometry.  Both are tables here rather than stylesheet rules, because
``shared.css`` is interpolated with handler state before it is parsed -- so the
Python side computes the numbers and the stylesheet only spends them.

Data sources, in the order each is tried:

CPU usage  : /proc/stat (delta) -> vmstat -> mpstat -> top
CPU temp   : /sys/class/hwmon -> /sys/class/thermal -> sensors
CPU clock  : /sys/.../cpufreq/scaling_cur_freq -> /proc/cpuinfo
RAM        : /proc/meminfo -> free -> top
Disk       : os.statvfs -> df
GPU        : nvidia-smi -> rocm-smi -> /sys/class/drm sysfs
Network    : /proc/net/dev (delta)
Battery    : /sys/class/power_supply
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Units ────────────────────────────────────────────────────────────────────

# The reference canvas the geometry tables are written against.  Real keys are
# 72-96 px while the PDK root font stays at 14 px, so sizing against the
# smallest key is the safe direction: a bigger key just gets more air.
REF_CANVAS = 72.0
PDK_ROOT_PX = 14.0


def pct(value: float) -> str:
    """A percentage-of-canvas length, as the stylesheet wants it."""
    return f"{value:.2f}%"


def em(value: float) -> str:
    """A font size in em against the 14 px PDK root."""
    return f"{value:.3f}em"


def px_of_em(value: float) -> float:
    """Height in pixels that *value* em occupies at the PDK root size."""
    return value * PDK_ROOT_PX


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# The renderer floors a box to whole pixels and cannot draw one narrower than
# that, so a fill this short is either widened to a sliver or dropped entirely.
# A visible box of zero width is not a faint box -- it is a crash.
MIN_VISIBLE_PCT = 150.0 / REF_CANVAS


def fill_length(span_pct: float, ratio: float) -> float:
    """*ratio* of *span_pct*, rounded away from a length that cannot draw."""
    length = span_pct * clamp(ratio, 0.0, 1.0)
    if length <= 0.0:
        return 0.0
    return max(length, MIN_VISIBLE_PCT)


# ── Colour ───────────────────────────────────────────────────────────────────

COLOR_OK = "#3fb950"
COLOR_WARN = "#d29922"
COLOR_CRIT = "#f85149"

# Longest form first: alternation is ordered, so listing #RGB first would let it
# match the first three digits of a #RRGGBB colour and read a different hue.
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})")


def _channels(color: Any) -> Optional[Tuple[int, int, int]]:
    """RGB bytes of the first hex colour in *color*, or ``None``.

    Reading the first stop is enough to judge a gradient's brightness.
    """
    match = _HEX_RE.search(str(color or ""))
    if not match:
        return None
    raw = match.group(0)[1:]
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def luminance(color: Any) -> Optional[float]:
    """Perceived brightness 0..1, or ``None`` when *color* holds no hex."""
    rgb = _channels(color)
    if rgb is None:
        return None
    r, g, b = (c / 255.0 for c in rgb)
    return 0.299 * r + 0.587 * g + 0.114 * b


def _shade(color: Any, *, to_dark: bool, amount: float = 0.5) -> str:
    """Blend *color* towards black or white, keeping its hue."""
    rgb = _channels(color)
    if rgb is None:
        return str(color)
    target = 0 if to_dark else 255
    return "#" + "".join(f"{int(c + (target - c) * amount):02x}" for c in rgb)


def mix(color: Any, other: Any, amount: float) -> str:
    """Blend *color* *amount* of the way towards *other*."""
    a = _channels(color)
    b = _channels(other)
    if a is None or b is None:
        return str(color)
    return "#" + "".join(f"{int(x + (y - x) * amount):02x}" for x, y in zip(a, b))


# How far an ink has to sit from the background, in perceived brightness, to
# still read on a 72 px key.  A quiet ink -- the bar track, the sub line -- is
# meant to be quiet, so the bar is set low: rescuing those would make a dark
# button louder than the theme it is based on.
_MIN_INK_DELTA = 0.20

# Ink roles and their substitutes as (on a dark background, on a light one).
_INK_SUBSTITUTES: Dict[str, Tuple[str, str]] = {
    "fg": ("#ffffff", "#15151b"),
    "dim": ("#b9b9c6", "#4a4a55"),
}
_TINT_INK = ("accent", "ok", "warn", "crit")


def relight(style: Dict[str, Any], background: str) -> None:
    """Rescue any ink that would vanish against *background*.

    Only called when the background comes from the button or the user's own
    colour field -- a theme that ships a light palette of its own keeps the ink
    its author chose.
    """
    bg_lum = luminance(background)
    if bg_lum is None:
        return
    light_bg = bg_lum >= 0.5

    for key, (on_dark, on_light) in _INK_SUBSTITUTES.items():
        ink = luminance(style.get(key))
        if ink is None or abs(ink - bg_lum) >= _MIN_INK_DELTA:
            continue
        style[key] = on_light if light_bg else on_dark

    for key in _TINT_INK:
        ink = luminance(style.get(key))
        if ink is None or abs(ink - bg_lum) >= _MIN_INK_DELTA:
            continue
        style[key] = _shade(style[key], to_dark=light_bg)

    # The track is a surface, not ink: lift it off the background rather than
    # swapping it for a fixed colour, so it stays a shade of the theme.
    track = luminance(style.get("track"))
    if track is not None and abs(track - bg_lum) < 0.12:
        style["track"] = _shade(background, to_dark=not light_bg, amount=0.18)


# ── Themes ───────────────────────────────────────────────────────────────────

# Everything a face needs to paint itself, at the values the original dark
# GitHub-ish look used.  A theme overrides the handful of keys it cares about.
#
#   bg / fg / dim   background, the big value's ink, the header and sub line
#   accent          the bar fill when the reading is not tinted by threshold
#   track           the unfilled part of the bar
#   ok/warn/crit    the threshold ramp, so a theme can keep its own palette
#   card            (x, y, w, h, fill, radius, border_w, border_c) or None
#   glow            (size, colour) laid under the big value, or None
_THEME_BASE: Dict[str, Any] = {
    "_label": "Classic",
    "bg": "linear-gradient(180deg, #0d1117, #161b22)",
    "fg": "#e6edf3",
    "dim": "#8b949e",
    "accent": "#58a6ff",
    "track": "#21262d",
    "ff": "DejaVu Sans",
    "wt": "bold",
    "hdr_wt": "bold",
    "ok": COLOR_OK,
    "warn": COLOR_WARN,
    "crit": COLOR_CRIT,
    "card": None,
    "glow": None,
    "upper": False,
    "bar_r": 3,
    "val_em": 1.45,
    "hdr_em": 0.64,
    "sub_em": 0.64,
}

THEMES: Dict[str, Dict[str, Any]] = {
    "classic": {"_label": "Classic"},
    "carbon": {
        "_label": "Carbon", "bg": "#16161a", "fg": "#f2f2f7", "dim": "#8a8a95",
        "accent": "#5ac8fa", "track": "#2a2a31",
    },
    "slate": {
        "_label": "Slate", "bg": "linear-gradient(160deg, #232733, #171a22)",
        "fg": "#ffffff", "dim": "#9aa0b4", "accent": "#00d1b2", "track": "#2f3442",
        "card": (5.0, 5.0, 90.0, 90.0, "transparent", 9, 1, "#333a4b"),
    },
    "light": {
        "_label": "Light", "bg": "#f5f6f8", "fg": "#16181d", "dim": "#6b7280",
        "accent": "#2f6fed", "track": "#d8dbe0", "wt": "bold",
        "ok": "#1a7f37", "warn": "#9a6700", "crit": "#cf222e",
    },
    "paper": {
        "_label": "Paper", "bg": "#f2efe6", "fg": "#1c1c1c", "dim": "#6a6558",
        "accent": "#d8362a", "track": "#ded9cb",
        "ok": "#3f7d3f", "warn": "#b07d15", "crit": "#c0392b",
    },
    "mono": {
        "_label": "Mono", "bg": "#101014", "fg": "#e6e6ee", "dim": "#6b6b7c",
        "accent": "#e6e6ee", "track": "#26262f",
        "ff": "DejaVu Sans Mono", "ok": "#c9c9d6", "warn": "#9a9aa8", "crit": "#ffffff",
    },
    "terminal": {
        "_label": "Terminal", "bg": "#04120a", "fg": "#33ff66", "dim": "#1f8a42",
        "accent": "#33ff66", "track": "#0b2b17", "ff": "DejaVu Sans Mono",
        "upper": True, "ok": "#33ff66", "warn": "#d7ff3b", "crit": "#ff5f5f",
    },
    "lcd": {
        "_label": "LCD", "bg": "#0d1a12", "fg": "#7dffb0", "dim": "#2f6b48",
        "accent": "#7dffb0", "track": "#122a1c", "ff": "DejaVu Sans Mono",
        "card": (3.0, 3.0, 94.0, 94.0, "#08120c", 6, 1, "#1e4630"),
        "ok": "#7dffb0", "warn": "#ffe066", "crit": "#ff6b6b",
    },
    "amber": {
        "_label": "Amber", "bg": "#12100a", "fg": "#ffb000", "dim": "#7a5a12",
        "accent": "#ffb000", "track": "#2a2110", "ff": "DejaVu Sans Mono",
        "glow": (5, "#ffb000"), "ok": "#ffb000", "warn": "#ff8c1a", "crit": "#ff4d3d",
    },
    "neon": {
        "_label": "Neon", "bg": "#0a0416", "fg": "#00e5ff", "dim": "#7a45c9",
        "accent": "#ff2bd6", "track": "#231041", "glow": (6, "#00e5ff"),
        "ok": "#3bffb0", "warn": "#ffe600", "crit": "#ff2bd6",
    },
    "midnight": {
        "_label": "Midnight", "bg": "linear-gradient(180deg, #16002e, #05000f)",
        "fg": "#d9c9ff", "dim": "#7a5fb0", "accent": "#9d7bff", "track": "#241348",
        "ok": "#7ee787", "warn": "#e3b341", "crit": "#ff7b72",
    },
    "ocean": {
        "_label": "Ocean", "bg": "linear-gradient(180deg, #071a2c, #0d3352)",
        "fg": "#e6f4ff", "dim": "#6f9dc4", "accent": "#35c3f0", "track": "#123c5c",
        "ok": "#3ddc97", "warn": "#ffc857", "crit": "#ff6b6b",
    },
    "sunset": {
        "_label": "Sunset", "bg": "linear-gradient(160deg, #ff7a45, #ff2e63)",
        "fg": "#ffffff", "dim": "#ffe0d5", "accent": "#ffffff", "track": "#a52a4a",
        "ok": "#ffffff", "warn": "#fff0a6", "crit": "#3d0011",
    },
    "blueprint": {
        "_label": "Blueprint", "bg": "#0a1f3d", "fg": "#d6e8ff", "dim": "#4f86c6",
        "accent": "#6fb8ff", "track": "#12335c",
        "card": (4.0, 4.0, 92.0, 92.0, "transparent", 2, 1, "#2f6fb8"),
        "ok": "#8fe388", "warn": "#ffd166", "crit": "#ff7a7a",
    },
    "nord": {
        "_label": "Nord", "bg": "#2e3440", "fg": "#eceff4", "dim": "#81a1c1",
        "accent": "#88c0d0", "track": "#3b4252",
        "ok": "#a3be8c", "warn": "#ebcb8b", "crit": "#bf616a",
    },
    "dracula": {
        "_label": "Dracula", "bg": "#282a36", "fg": "#f8f8f2", "dim": "#6272a4",
        "accent": "#bd93f9", "track": "#3a3d51",
        "ok": "#50fa7b", "warn": "#f1fa8c", "crit": "#ff5555",
    },
    "gruvbox": {
        "_label": "Gruvbox", "bg": "#282828", "fg": "#ebdbb2", "dim": "#928374",
        "accent": "#d79921", "track": "#3c3836",
        "ok": "#b8bb26", "warn": "#fabd2f", "crit": "#fb4934",
    },
    "solarized": {
        "_label": "Solarized", "bg": "#002b36", "fg": "#eee8d5", "dim": "#587e75",
        "accent": "#268bd2", "track": "#073642",
        "ok": "#859900", "warn": "#b58900", "crit": "#dc322f",
    },
}


def theme(key: str) -> Dict[str, Any]:
    """The full style dict for theme *key*, unknown names falling back."""
    merged = dict(_THEME_BASE)
    merged.update(THEMES.get(key) or THEMES["classic"])
    return merged


# ── Layouts ──────────────────────────────────────────────────────────────────

# Geometry, all in percentages of the canvas.
#
#   col             (x, y, w, h) of the text column
#   align           how the column's rows sit horizontally
#   rows            which of header / value / sub the layout draws
#   pad             (header, value, sub) top padding in px, to space the rows
#                   without a shared gap showing through a hidden one
#   bar             (x, y, w, h) of the horizontal bar, or None
#   vbar            (x, y, w, h) of the vertical bar, or None
#   spark           (x, y, w, h) of the history plot, or None
#   scale           multiplier on the theme's value size
_LAYOUT_BASE: Dict[str, Any] = {
    "_label": "Stat",
    "col": (0.0, 3.0, 100.0, 66.0),
    "align": "center",
    "rows": ("header", "value", "sub"),
    "pad": (0, 1, 1),
    "bar": (8.0, 80.0, 84.0, 5.0),
    "vbar": None,
    "spark": None,
    "scale": 1.0,
}

LAYOUTS: Dict[str, Dict[str, Any]] = {
    "stat": {"_label": "Stat"},
    "minimal": {
        "_label": "Minimal",
        "col": (0.0, 0.0, 100.0, 100.0),
        "rows": ("value",),
        "bar": (0.0, 95.0, 100.0, 5.0),
        "scale": 1.45,
    },
    "gauge": {
        "_label": "Gauge",
        "col": (0.0, 0.0, 100.0, 86.0),
        "rows": ("value", "sub"),
        "pad": (0, 0, 1),
        "bar": (0.0, 88.0, 100.0, 12.0),
        "scale": 1.2,
    },
    "split": {
        "_label": "Split",
        "col": (7.0, 0.0, 66.0, 100.0),
        "align": "start",
        "rows": ("header", "value", "sub"),
        "pad": (0, 1, 1),
        "bar": None,
        "vbar": (80.0, 9.0, 11.0, 82.0),
        "scale": 0.95,
    },
    "graph": {
        "_label": "Graph",
        "col": (0.0, 1.0, 100.0, 60.0),
        "rows": ("header", "value", "sub"),
        "pad": (0, 1, 1),
        "bar": None,
        "spark": (5.0, 62.0, 90.0, 33.0),
        "scale": 0.95,
    },
}

# How many samples the history plot keeps and draws.
SPARK_BARS = 14


def layout(key: str) -> Dict[str, Any]:
    """The full geometry dict for layout *key*, unknown names falling back."""
    merged = dict(_LAYOUT_BASE)
    merged.update(LAYOUTS.get(key) or LAYOUTS["stat"])
    return merged


# ── Text metrics ─────────────────────────────────────────────────────────────

# DejaVu Sans advance widths in em, for the glyph classes a readout uses.
# Sizing type from these keeps "12.4/32G" from running off a 72 px key without
# the handler having to know the canvas size.
_ADV_REGULAR = {"digit": 0.6362, "narrow": 0.3369, "space": 0.3179, "other": 0.64}
_ADV_BOLD = {"digit": 0.6958, "narrow": 0.3998, "space": 0.3481, "other": 0.70}
_NARROW = ":./|"


def text_em_width(text: str, bold: bool = False) -> float:
    """Approximate width of *text* in em at the current font."""
    adv = _ADV_BOLD if bold else _ADV_REGULAR
    total = 0.0
    for ch in text:
        if ch.isdigit():
            total += adv["digit"]
        elif ch in _NARROW:
            total += adv["narrow"]
        elif ch == " ":
            total += adv["space"]
        else:
            total += adv["other"]
    return total


def fit_em(text: str, avail_pct: float, cap_em: float, bold: bool = False) -> float:
    """Largest font size in em that fits *text* into *avail_pct* of the canvas."""
    width_em = text_em_width(text, bold)
    if width_em <= 0:
        return cap_em
    avail_px = REF_CANVAS * avail_pct / 100.0
    return max(0.4, min(cap_em, avail_px / width_em / PDK_ROOT_PX))


# ── Thresholds ───────────────────────────────────────────────────────────────

def threshold_color(
    value: Optional[float],
    warn: float,
    crit: float,
    style: Dict[str, Any],
    *,
    invert: bool = False,
) -> str:
    """The theme's ok / warn / crit ink for *value*.

    ``invert`` is for readings where *low* is the bad end -- a battery charge,
    free disk space -- so the same two gates read the other way round.
    """
    if value is None:
        return str(style["fg"])
    if invert:
        if value <= crit:
            return str(style["crit"])
        if value <= warn:
            return str(style["warn"])
        return str(style["ok"])
    if value >= crit:
        return str(style["crit"])
    if value >= warn:
        return str(style["warn"])
    return str(style["ok"])


def cfg_float(cfg: Dict[str, Any], key: str, fallback: float) -> float:
    """A numeric UI field, tolerant of the empty string and of junk."""
    try:
        raw = cfg.get(key)
        if raw is None or raw == "":
            return fallback
        return float(raw)
    except (TypeError, ValueError):
        return fallback


# ── Formatting ───────────────────────────────────────────────────────────────

def to_f(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def fmt_pct(value: Optional[float], decimals: bool = False) -> str:
    if value is None:
        return "--"
    return f"{value:.1f}%" if decimals else f"{value:.0f}%"


def fmt_temp(celsius: Optional[float], use_f: bool = False) -> str:
    if celsius is None:
        return ""
    return f"{to_f(celsius):.0f}°F" if use_f else f"{celsius:.0f}°C"


def fmt_size(gib: Optional[float]) -> str:
    """A capacity in the largest unit that keeps it under four characters."""
    if gib is None:
        return "--"
    if gib >= 1024:
        return f"{gib / 1024:.1f}T"
    if gib >= 100:
        return f"{gib:.0f}G"
    if gib >= 1:
        return f"{gib:.1f}G"
    return f"{gib * 1024:.0f}M"


def fmt_pair(used: Optional[float], total: Optional[float]) -> str:
    """``used/total`` in one unit, chosen from the larger of the two."""
    if used is None or total is None:
        return "--"
    if total >= 1024:
        return f"{used / 1024:.1f}/{total / 1024:.1f}T"
    if total >= 100:
        return f"{used:.0f}/{total:.0f}G"
    return f"{used:.1f}/{total:.0f}G"


def fmt_rate(bytes_per_s: Optional[float], bits: bool = False) -> str:
    """A transfer rate, scaled to K / M / G and suffixed with ``/s``."""
    if bytes_per_s is None:
        return "--"
    value = bytes_per_s * 8 if bits else bytes_per_s
    unit = "b" if bits else "B"
    step = 1000.0 if bits else 1024.0
    for suffix in ("", "K", "M", "G"):
        if value < step or suffix == "G":
            if suffix and value < 10:
                return f"{value:.1f}{suffix}{unit}/s"
            return f"{value:.0f}{suffix}{unit}/s"
        value /= step
    return f"{value:.0f}G{unit}/s"


def fmt_freq(mhz: Optional[float]) -> str:
    if mhz is None:
        return "--"
    if mhz >= 1000:
        return f"{mhz / 1000:.2f}G"
    return f"{mhz:.0f}M"


def fmt_duration(seconds: Optional[float]) -> str:
    """``1h20`` / ``45m`` -- short enough for a sub line on a 72 px key."""
    if seconds is None or seconds < 0:
        return ""
    minutes = int(seconds // 60)
    if minutes >= 60:
        return f"{minutes // 60}h{minutes % 60:02d}"
    return f"{minutes}m"


def fmt_watts(watts: Optional[float]) -> str:
    if watts is None:
        return ""
    return f"{watts:.0f}W" if watts >= 10 else f"{watts:.1f}W"


# ── History ──────────────────────────────────────────────────────────────────

# One ring buffer per button, so a Graph face plots its own mount point or its
# own network interface rather than whatever the last poll happened to read.
_HISTORY: Dict[str, List[float]] = {}


def push_history(key: str, value: Optional[float], size: int = SPARK_BARS) -> List[float]:
    """Append *value* to the *key* ring and return the whole ring."""
    ring = _HISTORY.setdefault(key, [])
    ring.append(0.0 if value is None else float(value))
    if len(ring) > size:
        del ring[: len(ring) - size]
    return ring


def history_key(cfg: Dict[str, Any], scope: str) -> str:
    """A ring identity: the button, or the function when the id is missing."""
    return f"{scope}:{cfg.get('_button_id', '?')}"


def read_history(key: str) -> List[float]:
    """The kept samples for *key* without adding one -- for a redraw."""
    return list(_HISTORY.get(key, []))


# ── Colour source ────────────────────────────────────────────────────────────

def apply_colors(style: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fold the button's colour settings into *style*, in place.

    ``"theme"`` keeps the palette the theme ships.  ``"button"`` hands the
    background over to the colour (or gradient) picker in the editor, and
    ``"custom"`` takes the three hex fields from the property panel.  Both of
    the latter run :func:`relight`, so ink that lands on a background too close
    to it is swapped for one that still reads.
    """
    source = str(cfg.get("color_source", "theme"))

    if source == "button":
        background = str(
            cfg.get("_button_gradient") or cfg.get("_button_color") or ""
        ).strip()
        if background:
            style["bg"] = background
            relight(style, background)
        return style

    if source == "custom":
        bg = str(cfg.get("custom_bg") or "").strip()
        fg = str(cfg.get("custom_fg") or "").strip()
        accent = str(cfg.get("custom_accent") or "").strip()
        if bg:
            style["bg"] = bg
            style["track"] = mix(bg, "#808080", 0.28)
            relight(style, bg)
        if fg:
            # The value colour also becomes the ramp's all-clear entry, so it
            # is what the face actually shows most of the time; warn and crit
            # still take over at the gates.
            style["fg"] = style["ok"] = fg
            style["dim"] = mix(fg, style["bg"] if _channels(style["bg"]) else "#808080", 0.45)
        if accent:
            style["accent"] = accent
    return style


# ── Face state ───────────────────────────────────────────────────────────────

_SLOTS = (1, 2, 3)

# Every name the stylesheet interpolates, at a value that draws nothing.  A
# layout fills in only the keys it uses, so anything belonging to another one
# resolves to a no-op instead of a stray literal in the CSS.
def _css_defaults() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "bg": "#000000",
        "card_x": "0%", "card_y": "0%", "card_w": "0%", "card_h": "0%",
        "card_c": "transparent", "card_r": "0",
        "card_bw": "0", "card_bc": "transparent",
        "col_x": "0%", "col_y": "0%", "col_w": "100%", "col_h": "100%",
        "col_al": "center",
        "bar_x": "0%", "bar_y": "0%", "bar_w": "0%", "bar_fw": "0%",
        "bar_h": "0", "bar_r": "0",
        "bar_track": "transparent", "bar_fill": "transparent",
        "vb_x": "0%", "vb_y": "0%", "vb_w": "0%", "vb_h": "0%", "vb_r": "0",
        "vb_track": "transparent", "vb_fill": "transparent",
        "vb_fy": "0%", "vb_fh": "0%",
        "g_w": "0%", "g_r": "0",
    }
    for n in _SLOTS:
        out.update({
            f"s{n}_t": "",
            f"s{n}_size": "0.64em",
            f"s{n}_c": "transparent",
            f"s{n}_wt": "normal",
            f"s{n}_ff": "DejaVu Sans",
            f"s{n}_al": "center",
            f"s{n}_pt": "0",
            f"s{n}_glow": "none",
        })
    for n in range(1, SPARK_BARS + 1):
        out.update({
            f"g{n}_x": "0%", f"g{n}_y": "0%", f"g{n}_h": "0%",
            f"g{n}_c": "transparent",
        })
    return out


def _spark_state(
    lay: Dict[str, Any],
    style: Dict[str, Any],
    samples: List[float],
    tint: Optional[str],
    gates: Optional[Tuple[float, float, bool]],
) -> Dict[str, Any]:
    """Geometry and ink for the history plot, one bar per kept sample."""
    box = lay.get("spark")
    if not box:
        return {}
    gx, gy, gw, gh = box
    slot_w = gw / SPARK_BARS
    bar_w = slot_w * 0.68
    # Older samples first, so a short ring leaves the left of the plot empty
    # and the newest reading always sits against the right edge.
    padded: List[Optional[float]] = (
        [None] * (SPARK_BARS - len(samples)) + list(samples[-SPARK_BARS:])
    )

    out: Dict[str, Any] = {"g_w": pct(max(bar_w, MIN_VISIBLE_PCT)), "g_r": "1"}
    for i, sample in enumerate(padded):
        n = i + 1
        left = gx + i * slot_w + (slot_w - bar_w) / 2
        if sample is None:
            out.update({f"g{n}_x": pct(left), f"g{n}_y": "0%",
                        f"g{n}_h": "0%", f"g{n}_c": "transparent"})
            continue
        height = max(MIN_VISIBLE_PCT, gh * clamp(sample, 0.0, 100.0) / 100.0)
        if gates is not None:
            warn, crit, invert = gates
            color = threshold_color(sample, warn, crit, style, invert=invert)
        else:
            color = tint or str(style["accent"])
        out.update({
            f"g{n}_x": pct(left),
            f"g{n}_y": pct(gy + gh - height),
            f"g{n}_h": pct(height),
            f"g{n}_c": color,
        })
    return out


def face_state(
    cfg: Dict[str, Any],
    *,
    header: str,
    value: str,
    sub: str,
    bar_pct: Optional[float],
    tint: Optional[str] = None,
    gates: Optional[Tuple[float, float, bool]] = None,
    samples: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """Turn one reading into the flat ``{key: value}`` state the face renders.

    *tint* is the threshold ink for this reading, or ``None`` to leave the
    value in the theme's own colour.  *gates* is the ``(warn, crit, invert)``
    triple the history plot re-runs per sample; *samples* is that history.
    """
    style = apply_colors(theme(str(cfg.get("theme", "classic"))), cfg)
    lay = layout(str(cfg.get("layout", "stat")))

    custom_header = str(cfg.get("header_text") or "").strip()
    if custom_header:
        header = custom_header
    if style["upper"]:
        header, sub = header.upper(), sub.upper()

    rows = lay["rows"]
    show_header = "header" in rows and bool(cfg.get("show_header", True))
    show_sub = "sub" in rows and bool(cfg.get("show_sub", True))
    show_bar = bool(cfg.get("show_bar", True))

    col_x, col_y, col_w, col_h = lay["col"]
    has_bar = show_bar and lay["bar"] is not None
    has_vbar = show_bar and lay["vbar"] is not None
    has_spark = lay["spark"] is not None
    if not (has_bar or has_spark):
        # Nothing below the column: let the text have the rest of the key.
        col_h = 100.0 - col_y

    state = _css_defaults()
    state["bg"] = style["bg"]
    state.update({
        "col_x": pct(col_x), "col_y": pct(col_y),
        "col_w": pct(col_w), "col_h": pct(col_h),
        "col_al": lay["align"],
    })

    card = style["card"]
    if card:
        cx, cy, cw, ch, fill, radius, bw, bc = card
        state.update({
            "card_x": pct(cx), "card_y": pct(cy),
            "card_w": pct(cw), "card_h": pct(ch),
            "card_c": fill, "card_r": str(radius),
            "card_bw": str(bw), "card_bc": bc,
        })

    ink = tint or str(style["fg"])
    sub_ink = tint or str(style["dim"])
    align = "left" if lay["align"] == "start" else "center"
    pad_header, pad_value, pad_sub = lay["pad"]
    val_cap = float(style["val_em"]) * float(lay["scale"])

    texts = (
        (1, header if show_header else "", style["hdr_em"], str(style["dim"]),
         style["hdr_wt"], pad_header),
        (2, value, val_cap, ink, style["wt"], pad_value),
        (3, sub if show_sub else "", style["sub_em"], sub_ink, "normal", pad_sub),
    )
    for n, text, cap_em, color, weight, pad in texts:
        size = fit_em(text, col_w * 0.94, float(cap_em), weight == "bold")
        state.update({
            f"s{n}_t": text,
            f"s{n}_size": em(size),
            f"s{n}_c": color if text else "transparent",
            f"s{n}_wt": weight,
            f"s{n}_ff": style["ff"],
            f"s{n}_al": align,
            # A row the user turned off keeps no padding: the spacing belongs
            # to the row above it, and charging it anyway would push the rest
            # of the column off centre.
            f"s{n}_pt": str(pad if text else 0),
        })
    glow = style["glow"]
    if glow and value:
        state["s2_glow"] = f"{glow[0]} {glow[1]}"

    filled = clamp(0.0 if bar_pct is None else bar_pct, 0.0, 100.0)
    accent = tint or str(style["accent"])
    if has_bar:
        bx, by, bw_, bh = lay["bar"]
        fill_w = fill_length(bw_, filled / 100.0)
        state.update({
            "bar_x": pct(bx), "bar_y": pct(by), "bar_w": pct(bw_),
            "bar_fw": pct(fill_w),
            "bar_h": f"{bh:g}", "bar_r": str(style["bar_r"]),
            "bar_track": style["track"],
            "bar_fill": accent if fill_w else "transparent",
        })
    if has_vbar:
        vx, vy, vw, vh = lay["vbar"]
        fill_h = fill_length(vh, filled / 100.0)
        state.update({
            "vb_x": pct(vx), "vb_y": pct(vy), "vb_w": pct(vw), "vb_h": pct(vh),
            "vb_r": str(style["bar_r"]),
            "vb_track": style["track"],
            "vb_fill": accent if fill_h else "transparent",
            "vb_fy": pct(vy + vh - fill_h), "vb_fh": pct(fill_h),
        })
    if has_spark:
        state.update(_spark_state(lay, style, samples or [], tint, gates))
    return state


def error_state(cfg: Dict[str, Any], header: str, message: str = "N/A") -> Dict[str, Any]:
    """The face a handler shows when its backend returned nothing."""
    return face_state(
        cfg, header=header, value=message, sub="", bar_pct=None, tint=None,
    )


def tint_for(
    cfg: Dict[str, Any],
    *,
    reading: Optional[float],
    temp_c: Optional[float] = None,
    warn: float,
    crit: float,
    temp_warn: float = 65.0,
    temp_crit: float = 85.0,
    invert: bool = False,
) -> Tuple[Optional[str], Optional[Tuple[float, float, bool]]]:
    """The threshold ink for this reading, and the gates a history plot reuses.

    ``Tint`` is the button's own setting: ``auto`` colours by the reading the
    bar tracks, ``temp`` by the temperature instead, and ``off`` leaves the
    value in the theme's own ink.  Tinting by temperature returns no gates,
    because the plotted samples are the bar's reading and colouring those
    against a temperature scale would be meaningless.
    """
    mode = str(cfg.get("tint", "auto"))
    if mode == "off":
        return None, None
    style = apply_colors(theme(str(cfg.get("theme", "classic"))), cfg)
    if mode == "temp":
        return threshold_color(temp_c, temp_warn, temp_crit, style), None
    return (
        threshold_color(reading, warn, crit, style, invert=invert),
        (warn, crit, invert),
    )




def _run(cmd: List[str], timeout: int = 4) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=timeout,
        )
        return proc.returncode == 0, proc.stdout
    except Exception:
        return False, ""


# ══ CPU USAGE ═════════════════════════════════════════════════════════════════

_CPU_CHIPS = ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal", "k8temp")
_proc_stat_prev: Dict[str, Tuple[int, int]] = {}


def _cpu_via_proc_stat() -> Optional[float]:
    try:
        text = Path("/proc/stat").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        if not line.startswith("cpu "):
            continue
        try:
            vals = [int(x) for x in line.split()[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            total = sum(vals)
        except (IndexError, ValueError):
            return None
        prev = _proc_stat_prev.get("cpu")
        _proc_stat_prev["cpu"] = (total, idle)
        if prev is None:
            return None
        d_total = total - prev[0]
        d_idle = idle - prev[1]
        if d_total <= 0:
            return None
        return round((1.0 - d_idle / d_total) * 100.0, 1)
    return None


def _cpu_via_vmstat() -> Optional[float]:
    if not shutil.which("vmstat"):
        return None
    ok, out = _run(["vmstat", "1", "2"])
    if not ok:
        return None
    lines = [l for l in out.splitlines()
             if l.strip() and not l.startswith(("procs", "r ", " r"))]
    if not lines:
        return None
    try:
        parts = lines[-1].split()
        idle = float(parts[14])
        return round(100.0 - idle, 1)
    except (IndexError, ValueError):
        return None


def _cpu_via_mpstat() -> Optional[float]:
    if not shutil.which("mpstat"):
        return None
    ok, out = _run(["mpstat", "1", "1"])
    if not ok:
        return None
    for line in reversed(out.splitlines()):
        if "all" in line or re.search(r"\d+\.\d+", line):
            parts = line.split()
            try:
                idle = float(parts[-1])
                return round(100.0 - idle, 1)
            except (IndexError, ValueError):
                continue
    return None


def _cpu_via_top() -> Optional[float]:
    ok, out = _run(["top", "-bn1"])
    if not ok:
        return None
    for line in out.splitlines():
        if re.search(r"%?Cpu", line, re.IGNORECASE):
            m = re.search(r"([\d.]+)\s+id", line)
            if m:
                return round(100.0 - float(m.group(1)), 1)
    return None


def cpu_pct(backend: str = "auto") -> Optional[float]:
    """Return CPU usage % using the selected or best available source."""
    if backend in ("procstat", "htop"):
        return _cpu_via_proc_stat()
    if backend == "vmstat":
        return _cpu_via_vmstat()
    if backend == "mpstat":
        return _cpu_via_mpstat()
    if backend == "top":
        return _cpu_via_top()
    return (
        _cpu_via_proc_stat()
        or _cpu_via_vmstat()
        or _cpu_via_mpstat()
        or _cpu_via_top()
    )


# ══ CPU TEMPERATURE ══════════════════════════════════════════════════════════

def _temp_via_hwmon() -> Optional[float]:
    base = Path("/sys/class/hwmon")
    if not base.exists():
        return None
    cpu_temps: List[float] = []
    all_temps: List[float] = []
    for hwmon in sorted(base.iterdir()):
        try:
            name = (hwmon / "name").read_text().strip().lower()
        except OSError:
            name = ""
        is_cpu = any(name.startswith(k) for k in _CPU_CHIPS)
        for f in sorted(hwmon.glob("temp*_input")):
            try:
                val = int(f.read_text().strip()) / 1000.0
                all_temps.append(val)
                if is_cpu:
                    cpu_temps.append(val)
            except (OSError, ValueError):
                pass
    candidates = cpu_temps if cpu_temps else all_temps
    return max(candidates) if candidates else None


def _temp_via_thermal_zone() -> Optional[float]:
    base = Path("/sys/class/thermal")
    if not base.exists():
        return None
    cpu_temps: List[float] = []
    all_temps: List[float] = []
    for zone in sorted(base.glob("thermal_zone*")):
        try:
            zone_type = (zone / "type").read_text().strip().lower()
            raw = int((zone / "temp").read_text().strip())
            val = raw / 1000.0
            all_temps.append(val)
            if any(k in zone_type for k in ("cpu", "pkg", "soc", "core", "x86")):
                cpu_temps.append(val)
        except (OSError, ValueError):
            pass
    candidates = cpu_temps if cpu_temps else all_temps
    return max(candidates) if candidates else None


def _temp_via_sensors() -> Optional[float]:
    if not shutil.which("sensors"):
        return None
    ok, out = _run(["sensors", "-j"])
    if not ok or not out.strip():
        return None
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None
    cpu_temps: List[float] = []
    all_temps: List[float] = []
    for chip_name, chip in data.items():
        if not isinstance(chip, dict):
            continue
        is_cpu = any(chip_name.lower().startswith(k) for k in _CPU_CHIPS)
        for feat_name, feat in chip.items():
            if feat_name == "Adapter" or not isinstance(feat, dict):
                continue
            for sub_key, val in feat.items():
                if sub_key.endswith("_input") and isinstance(val, (int, float)):
                    temp = float(val)
                    all_temps.append(temp)
                    if is_cpu:
                        cpu_temps.append(temp)
    candidates = cpu_temps if cpu_temps else all_temps
    return max(candidates) if candidates else None


def cpu_temp_c() -> Optional[float]:
    """Return the highest CPU temperature in °C."""
    return (
        _temp_via_hwmon()
        or _temp_via_thermal_zone()
        or _temp_via_sensors()
    )


# ══ RAM ══════════════════════════════════════════════════════════════════════

def _ram_via_proc_meminfo() -> Optional[Tuple[float, float, float]]:
    try:
        kv: Dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                kv[parts[0].rstrip(":")] = int(parts[1])
        total_kb = kv["MemTotal"]
        avail_kb = kv.get("MemAvailable", kv.get("MemFree", 0))
        used_kb = total_kb - avail_kb
        pct = round(used_kb / total_kb * 100.0, 1)
        factor = 1024 ** 2
        return (used_kb / factor, total_kb / factor, pct)
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        return None


def _ram_via_free() -> Optional[Tuple[float, float, float]]:
    if not shutil.which("free"):
        return None
    ok, out = _run(["free", "-b"])
    if not ok:
        return None
    for line in out.splitlines():
        if not line.startswith("Mem:"):
            continue
        try:
            parts = line.split()
            total = float(parts[1])
            avail = float(parts[6]) if len(parts) > 6 else float(parts[3])
            used = total - avail
            pct = round(used / total * 100.0, 1)
            gib = 1024 ** 3
            return (used / gib, total / gib, pct)
        except (IndexError, ValueError, ZeroDivisionError):
            return None
    return None


def _ram_via_top() -> Optional[Tuple[float, float, float]]:
    ok, out = _run(["top", "-bn1"])
    if not ok:
        return None
    for line in out.splitlines():
        if "Mem" not in line or "total" not in line:
            continue
        m_total = re.search(r"([\d.]+)\s+total", line)
        m_used = re.search(r"([\d.]+)\s+used", line)
        if not (m_total and m_used):
            continue
        try:
            factor = 1024 ** 3 if "GiB" in line else (1024 if "KiB" in line else 1024 ** 2)
            total_bytes = float(m_total.group(1)) * factor
            used_bytes = float(m_used.group(1)) * factor
            pct = round(used_bytes / total_bytes * 100.0, 1)
            gib = 1024 ** 3
            return (used_bytes / gib, total_bytes / gib, pct)
        except (ValueError, ZeroDivisionError):
            return None
    return None


def ram_stats(backend: str = "auto") -> Optional[Tuple[float, float, float]]:
    """Return (used_gib, total_gib, pct) using the best available source."""
    if backend in ("procmeminfo", "htop"):
        return _ram_via_proc_meminfo()
    if backend == "free":
        return _ram_via_free()
    if backend == "top":
        return _ram_via_top()
    return (
        _ram_via_proc_meminfo()
        or _ram_via_free()
        or _ram_via_top()
    )



# ══ CPU CLOCK, LOAD AND CORES ════════════════════════════════════════════════

def cpu_freq_mhz() -> Optional[float]:
    """Mean current core clock in MHz.

    ``cpufreq`` is per-core and always current; ``/proc/cpuinfo`` is the
    fallback for kernels built without the governor exposed in sysfs.
    """
    base = Path("/sys/devices/system/cpu")
    khz: List[float] = []
    if base.exists():
        for cpu in sorted(base.glob("cpu[0-9]*/cpufreq/scaling_cur_freq")):
            try:
                khz.append(float(cpu.read_text().strip()))
            except (OSError, ValueError):
                pass
    if khz:
        return sum(khz) / len(khz) / 1000.0

    try:
        mhz = [
            float(line.split(":", 1)[1])
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.lower().startswith("cpu mhz")
        ]
    except (OSError, IndexError, ValueError):
        return None
    return sum(mhz) / len(mhz) if mhz else None


def cpu_core_count() -> Optional[int]:
    """Logical processor count, counted where the kernel lists them."""
    try:
        count = sum(
            1 for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("processor")
        )
    except OSError:
        return None
    return count or None


def load_avg() -> Optional[Tuple[float, float, float]]:
    """The 1 / 5 / 15 minute load averages."""
    try:
        parts = Path("/proc/loadavg").read_text().split()
        return float(parts[0]), float(parts[1]), float(parts[2])
    except (OSError, IndexError, ValueError):
        return None


def uptime_seconds() -> Optional[float]:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, IndexError, ValueError):
        return None


# ══ SWAP ═════════════════════════════════════════════════════════════════════

def swap_stats() -> Optional[Tuple[float, float, float]]:
    """(used_gib, total_gib, pct) for swap, or ``None`` when there is none."""
    try:
        kv: Dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                kv[parts[0].rstrip(":")] = int(parts[1])
        total_kb = kv.get("SwapTotal", 0)
        if total_kb <= 0:
            return None
        free_kb = kv.get("SwapFree", 0)
        used_kb = total_kb - free_kb
        factor = 1024 ** 2
        return (used_kb / factor, total_kb / factor,
                round(used_kb / total_kb * 100.0, 1))
    except (OSError, ValueError, ZeroDivisionError):
        return None

# ══ DISK ═════════════════════════════════════════════════════════════════════

def _disk_via_statvfs(path: str) -> Optional[Tuple[float, float, float]]:
    try:
        st = os.statvfs(path)
        total_bytes = st.f_frsize * st.f_blocks
        free_bytes = st.f_frsize * st.f_bavail
        used_bytes = total_bytes - free_bytes
        pct = round(used_bytes / total_bytes * 100.0, 1)
        gib = 1024 ** 3
        return (used_bytes / gib, total_bytes / gib, pct)
    except (OSError, ZeroDivisionError):
        return None


def _disk_via_df(path: str) -> Optional[Tuple[float, float, float]]:
    ok, out = _run(["df", "-B1", path])
    if not ok or not out.strip():
        return None
    try:
        lines = out.strip().splitlines()
        data_line = " ".join(lines[1:])
        parts = data_line.split()
        total_bytes = float(parts[1])
        used_bytes = float(parts[2])
        pct = float(parts[4].rstrip("%"))
        gib = 1024 ** 3
        return (used_bytes / gib, total_bytes / gib, pct)
    except (IndexError, ValueError):
        return None


def disk_stats(path: str, backend: str = "auto") -> Optional[Tuple[float, float, float]]:
    """Return (used_gib, total_gib, pct) for the given mount point."""
    if backend == "statvfs":
        return _disk_via_statvfs(path)
    if backend == "df":
        return _disk_via_df(path)
    return _disk_via_statvfs(path) or _disk_via_df(path)

# ══ GPU ══════════════════════════════════════════════════════════════════════

# Every GPU backend answers with the same shape, so the handler never has to
# know which one replied.  A key the backend could not read is ``None`` rather
# than absent, so a caller can tell "no such reading" from "zero".
def _gpu_blank() -> Dict[str, Any]:
    return {
        "temp_c": None, "util_pct": None,
        "mem_used_gib": None, "mem_total_gib": None,
        "power_w": None, "name": "",
    }


def _num(raw: Any) -> Optional[float]:
    """A float from a tool's cell, treating ``N/A`` and blanks as missing."""
    text = str(raw or "").strip().strip("[]")
    if not text or text.lower().startswith(("n/a", "unsupported", "unknown")):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def nvidia_info(index: int = 0) -> Optional[Dict[str, Any]]:
    """nvidia-smi: every reading for one NVIDIA GPU, in a single query."""
    if not shutil.which("nvidia-smi"):
        return None
    ok, out = _run([
        "nvidia-smi",
        "--query-gpu=temperature.gpu,utilization.gpu,memory.used,"
        "memory.total,power.draw,name",
        "--format=csv,noheader,nounits",
    ])
    rows = [l for l in out.strip().splitlines() if l.strip()] if ok else []
    if not rows:
        return None
    parts = rows[min(max(index, 0), len(rows) - 1)].split(",")
    parts += [""] * (6 - len(parts))

    info = _gpu_blank()
    mib = 1024.0
    info["temp_c"] = _num(parts[0])
    info["util_pct"] = _num(parts[1])
    used, total = _num(parts[2]), _num(parts[3])
    info["mem_used_gib"] = used / mib if used is not None else None
    info["mem_total_gib"] = total / mib if total is not None else None
    info["power_w"] = _num(parts[4])
    info["name"] = parts[5].strip()
    return info if info["temp_c"] is not None or info["util_pct"] is not None else None


# rocm-smi's CSV header names have moved between releases, so the columns are
# matched on what they contain rather than on an exact string.
_ROCM_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("temp_c", r"temperature.*(edge|junction|sensor)|^temp"),
    ("util_pct", r"gpu\s*use|gpu\s*util"),
    ("power_w", r"power"),
    ("mem_pct", r"memory\s*use|vram.*use"),
)


def amd_info(index: int = 0) -> Optional[Dict[str, Any]]:
    """rocm-smi: the same readings for an AMD card, matched off the header."""
    if not shutil.which("rocm-smi"):
        return None
    ok, out = _run([
        "rocm-smi", "--showtemp", "--showuse", "--showmemuse", "--showpower",
        "--csv",
    ])
    rows = [l for l in out.strip().splitlines() if l.strip()] if ok else []
    if len(rows) < 2:
        return None

    header = [c.strip().lower() for c in rows[0].split(",")]
    columns: Dict[str, int] = {}
    for field, pattern in _ROCM_COLUMNS:
        for i, cell in enumerate(header):
            if re.search(pattern, cell):
                columns[field] = i
                break

    cards = rows[1:]
    parts = [c.strip() for c in cards[min(max(index, 0), len(cards) - 1)].split(",")]

    def cell(field: str) -> Optional[float]:
        i = columns.get(field)
        return _num(parts[i]) if i is not None and i < len(parts) else None

    info = _gpu_blank()
    info["temp_c"] = cell("temp_c")
    info["util_pct"] = cell("util_pct")
    info["power_w"] = cell("power_w")
    # rocm-smi reports memory as a percentage, so there is no byte total to
    # show alongside it; the handler falls back to the percentage on its own.
    info["mem_pct"] = cell("mem_pct")
    if info["temp_c"] is None and info["util_pct"] is None:
        return None
    return info


def sysfs_gpu_info(index: int = 0) -> Optional[Dict[str, Any]]:
    """/sys/class/drm sysfs: what nouveau, amdgpu and i915 expose directly."""
    drm = Path("/sys/class/drm")
    if not drm.exists():
        return None
    cards = [c for c in sorted(drm.glob("card[0-9]*")) if (c / "device").is_dir()]
    if not cards:
        return None
    device = cards[min(max(index, 0), len(cards) - 1)] / "device"

    def read(path: Path) -> Optional[float]:
        try:
            return float(path.read_text().strip())
        except (OSError, ValueError):
            return None

    info = _gpu_blank()
    for hwmon in sorted(device.glob("hwmon/hwmon*")):
        milli = read(hwmon / "temp1_input")
        if milli is not None:
            info["temp_c"] = milli / 1000.0
        micro = read(hwmon / "power1_average")
        if micro is not None:
            info["power_w"] = micro / 1e6
        if info["temp_c"] is not None:
            break

    info["util_pct"] = read(device / "gpu_busy_percent")
    gib = float(1024 ** 3)
    used = read(device / "mem_info_vram_used")
    total = read(device / "mem_info_vram_total")
    info["mem_used_gib"] = used / gib if used is not None else None
    info["mem_total_gib"] = total / gib if total is not None else None

    if info["temp_c"] is None and info["util_pct"] is None:
        return None
    return info


def gpu_info(backend: str = "auto", index: int = 0) -> Optional[Dict[str, Any]]:
    """Readings for one GPU from the selected or best available backend."""
    if backend == "nvidia":
        return nvidia_info(index)
    if backend == "amd":
        return amd_info(index)
    if backend == "sysfs":
        return sysfs_gpu_info(index)
    return nvidia_info(index) or amd_info(index) or sysfs_gpu_info(index)

# ══ NETWORK ══════════════════════════════════════════════════════════════════

# Interfaces that carry no traffic worth watching, or that only mirror it.
_NET_SKIP = re.compile(r"^(lo|docker\d|br-|veth|virbr|tun\d|tap\d|vmnet)")

# Last (timestamp, rx, tx) per button, since a rate is a difference and the
# poller gives us one sample at a time.
_NET_PREV: Dict[str, Tuple[float, int, int]] = {}


def net_interfaces() -> List[str]:
    """Interface names the kernel lists, the loopback and bridges last."""
    try:
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
    except OSError:
        return []
    names = [line.split(":", 1)[0].strip() for line in lines if ":" in line]
    real = [n for n in names if not _NET_SKIP.match(n)]
    return real + [n for n in names if n not in real]


def net_counters(iface: str = "") -> Optional[Tuple[int, int]]:
    """Cumulative (rx, tx) bytes for *iface*, or for every real one summed."""
    try:
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
    except OSError:
        return None
    want = (iface or "").strip()
    rx = tx = 0
    found = False
    for line in lines:
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        if want:
            if name != want:
                continue
        elif _NET_SKIP.match(name):
            continue
        fields = rest.split()
        if len(fields) < 9:
            continue
        try:
            rx += int(fields[0])
            tx += int(fields[8])
        except ValueError:
            continue
        found = True
    return (rx, tx) if found else None


def net_rates(key: str, iface: str = "") -> Optional[Tuple[float, float]]:
    """Bytes per second (down, up) since this button's previous poll.

    The first poll after a load has nothing to subtract from and reports zero,
    and so does a counter that went backwards -- an interface that was reset or
    renamed, which would otherwise show as one enormous spike.
    """
    counters = net_counters(iface)
    if counters is None:
        return None
    now = time.monotonic()
    rx, tx = counters
    prev = _NET_PREV.get(key)
    _NET_PREV[key] = (now, rx, tx)
    if prev is None:
        return (0.0, 0.0)
    elapsed = now - prev[0]
    if elapsed <= 0 or rx < prev[1] or tx < prev[2]:
        return (0.0, 0.0)
    return ((rx - prev[1]) / elapsed, (tx - prev[2]) / elapsed)


# ══ BATTERY ══════════════════════════════════════════════════════════════════

def battery_info() -> Optional[Dict[str, Any]]:
    """Charge, status, draw and estimated time left for the first battery."""
    base = Path("/sys/class/power_supply")
    if not base.exists():
        return None

    def read(path: Path) -> Optional[str]:
        try:
            return path.read_text().strip()
        except OSError:
            return None

    def number(path: Path) -> Optional[float]:
        raw = read(path)
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None

    for entry in sorted(base.iterdir()):
        if (read(entry / "type") or "").lower() != "battery":
            continue
        status = (read(entry / "status") or "Unknown").strip()
        charge = number(entry / "capacity")

        # Laptops report either energy (µWh + µW) or charge (µAh + µA); the
        # latter needs the voltage to become watts.
        energy_now = number(entry / "energy_now")
        energy_full = number(entry / "energy_full")
        power_now = number(entry / "power_now")
        volts = number(entry / "voltage_now")
        if energy_now is None and volts:
            charge_now = number(entry / "charge_now")
            charge_full = number(entry / "charge_full")
            current = number(entry / "current_now")
            if charge_now is not None:
                energy_now = charge_now * volts / 1e6
            if charge_full is not None:
                energy_full = charge_full * volts / 1e6
            if current is not None:
                power_now = current * volts / 1e6

        if charge is None and energy_now and energy_full:
            charge = energy_now / energy_full * 100.0

        watts = power_now / 1e6 if power_now else None
        seconds: Optional[float] = None
        if watts and watts > 0 and energy_now is not None:
            if status.lower() == "charging" and energy_full is not None:
                seconds = max(0.0, energy_full - energy_now) / power_now * 3600.0
            elif status.lower() == "discharging":
                seconds = energy_now / power_now * 3600.0

        return {
            "charge_pct": charge,
            "status": status,
            "power_w": watts,
            "seconds_left": seconds,
        }
    return None


# ══ EDITOR ENDPOINTS ═════════════════════════════════════════════════════════

def api_interfaces(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """Interface names for the Network readout's picker.

    Reached at ``GET /api/plugins/no.pydeck.system-monitor/api/interfaces``.
    The blank first entry is the default -- every real interface summed — so a
    button works before the user has chosen anything.
    """
    options = [{"label": "All interfaces", "value": ""}]
    options += [{"label": name, "value": name} for name in net_interfaces()]
    return options
