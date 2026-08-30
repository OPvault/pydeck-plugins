"""Clock -- analog and digital clock faces, world clocks and countdown timers.

Everything visual is driven from here: the handlers pick a style out of
:data:`ANALOG_STYLES` / :data:`DIGITAL_STYLES`, hand it the current time plus the
button's config, and get back a flat ``{key: value}`` state dict.  The templates
are static markup; ``shared.css`` is where the ``{placeholder}`` values land,
because the renderer interpolates state into the stylesheet as well as into
element text.

Geometry is expressed in percentages of the button canvas so a face looks the
same on a 72 px key and a 96 px XL key.  Type is sized in ``em`` against the
14 px PDK root, which is how every other PDK plugin sizes text.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

# (IANA zone, menu label).  The label doubles as the default city caption, so
# it is the bare place name rather than the zone id.
CITIES: List[Tuple[str, str]] = [
    ("local", "Local (System)"),
    ("UTC", "UTC"),
    ("Pacific/Honolulu", "Honolulu"),
    ("America/Anchorage", "Anchorage"),
    ("America/Los_Angeles", "Los Angeles"),
    ("America/Vancouver", "Vancouver"),
    ("America/Tijuana", "Tijuana"),
    ("America/Phoenix", "Phoenix"),
    ("America/Denver", "Denver"),
    ("America/Edmonton", "Edmonton"),
    ("America/Chicago", "Chicago"),
    ("America/Winnipeg", "Winnipeg"),
    ("America/Mexico_City", "Mexico City"),
    ("America/Guatemala", "Guatemala City"),
    ("America/New_York", "New York"),
    ("America/Toronto", "Toronto"),
    ("America/Detroit", "Detroit"),
    ("America/Havana", "Havana"),
    ("America/Panama", "Panama City"),
    ("America/Bogota", "Bogota"),
    ("America/Lima", "Lima"),
    ("America/Caracas", "Caracas"),
    ("America/Halifax", "Halifax"),
    ("America/Santiago", "Santiago"),
    ("America/La_Paz", "La Paz"),
    ("America/Asuncion", "Asuncion"),
    ("America/Sao_Paulo", "Sao Paulo"),
    ("America/Argentina/Buenos_Aires", "Buenos Aires"),
    ("America/Montevideo", "Montevideo"),
    ("America/St_Johns", "St. John's"),
    ("Atlantic/Azores", "Azores"),
    ("Atlantic/Reykjavik", "Reykjavik"),
    ("Europe/Lisbon", "Lisbon"),
    ("Europe/Dublin", "Dublin"),
    ("Europe/London", "London"),
    ("Africa/Casablanca", "Casablanca"),
    ("Africa/Lagos", "Lagos"),
    ("Africa/Algiers", "Algiers"),
    ("Europe/Madrid", "Madrid"),
    ("Europe/Paris", "Paris"),
    ("Europe/Brussels", "Brussels"),
    ("Europe/Amsterdam", "Amsterdam"),
    ("Europe/Berlin", "Berlin"),
    ("Europe/Zurich", "Zurich"),
    ("Europe/Vienna", "Vienna"),
    ("Europe/Prague", "Prague"),
    ("Europe/Rome", "Rome"),
    ("Europe/Copenhagen", "Copenhagen"),
    ("Europe/Oslo", "Oslo"),
    ("Europe/Stockholm", "Stockholm"),
    ("Europe/Warsaw", "Warsaw"),
    ("Europe/Budapest", "Budapest"),
    ("Europe/Belgrade", "Belgrade"),
    ("Europe/Malta", "Malta"),
    ("Africa/Cairo", "Cairo"),
    ("Africa/Johannesburg", "Johannesburg"),
    ("Europe/Athens", "Athens"),
    ("Europe/Helsinki", "Helsinki"),
    ("Europe/Bucharest", "Bucharest"),
    ("Europe/Kyiv", "Kyiv"),
    ("Europe/Riga", "Riga"),
    ("Asia/Jerusalem", "Jerusalem"),
    ("Africa/Nairobi", "Nairobi"),
    ("Europe/Istanbul", "Istanbul"),
    ("Europe/Moscow", "Moscow"),
    ("Asia/Riyadh", "Riyadh"),
    ("Asia/Baghdad", "Baghdad"),
    ("Asia/Tehran", "Tehran"),
    ("Asia/Dubai", "Dubai"),
    ("Asia/Baku", "Baku"),
    ("Asia/Karachi", "Karachi"),
    ("Asia/Tashkent", "Tashkent"),
    ("Asia/Kolkata", "Mumbai / Delhi"),
    ("Asia/Colombo", "Colombo"),
    ("Asia/Kathmandu", "Kathmandu"),
    ("Asia/Dhaka", "Dhaka"),
    ("Asia/Yangon", "Yangon"),
    ("Asia/Bangkok", "Bangkok"),
    ("Asia/Jakarta", "Jakarta"),
    ("Asia/Ho_Chi_Minh", "Ho Chi Minh City"),
    ("Asia/Singapore", "Singapore"),
    ("Asia/Kuala_Lumpur", "Kuala Lumpur"),
    ("Asia/Manila", "Manila"),
    ("Asia/Hong_Kong", "Hong Kong"),
    ("Asia/Taipei", "Taipei"),
    ("Asia/Shanghai", "Shanghai"),
    ("Australia/Perth", "Perth"),
    ("Asia/Seoul", "Seoul"),
    ("Asia/Tokyo", "Tokyo"),
    ("Australia/Adelaide", "Adelaide"),
    ("Australia/Brisbane", "Brisbane"),
    ("Australia/Sydney", "Sydney"),
    ("Australia/Melbourne", "Melbourne"),
    ("Pacific/Guadalcanal", "Honiara"),
    ("Pacific/Auckland", "Auckland"),
    ("Pacific/Fiji", "Suva"),
]

_CITY_LABELS: Dict[str, str] = {tz: label for tz, label in CITIES}


def now_in(zone_name: str, cfg: Dict[str, Any]) -> datetime:
    """Current time in *zone_name*, or the developer emulated clock's instant.

    ``_dev_time`` is injected by the core when the emulated-clock developer
    option is on (``""`` otherwise). It is a naive wall-clock stamp and is taken
    as the time this face should *display*, so a fixed value renders the same on
    every key regardless of the zone each one is set to -- which is the point
    when the frozen clock exists to make exported images reproducible.
    """
    stamp = str(cfg.get("_dev_time") or "").strip()
    if stamp:
        try:
            return datetime.fromisoformat(stamp).replace(tzinfo=resolve_zone(zone_name))
        except ValueError:
            pass
    return datetime.now(resolve_zone(zone_name))


def resolve_zone(name: str) -> Optional[ZoneInfo]:
    """Return a :class:`ZoneInfo` for *name*, or ``None`` for system local time."""
    name = (name or "local").strip()
    if not name or name == "local":
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def zone_label(name: str) -> str:
    """Human label for a zone: the curated city name, else the last path part."""
    name = (name or "local").strip()
    if name in _CITY_LABELS:
        return _CITY_LABELS[name]
    return name.rsplit("/", 1)[-1].replace("_", " ")


# ---------------------------------------------------------------------------
# Text metrics
# ---------------------------------------------------------------------------

# DejaVu Sans advance widths in em, for the handful of glyph classes a clock
# face uses.  Sizing type from these keeps a face from overflowing the key
# without the handler having to know the canvas size.
_ADV_REGULAR = {"digit": 0.6362, "colon": 0.3369, "space": 0.3179, "other": 0.64}
_ADV_BOLD = {"digit": 0.6958, "colon": 0.3998, "space": 0.3481, "other": 0.70}

# Reference canvas the fitting maths assumes.  Real canvases are 72-96 px while
# the PDK root font stays at 14 px, so fitting against the smallest key size is
# the safe direction: wider keys simply get a little more breathing room.
REF_CANVAS = 72.0
PDK_ROOT_PX = 14.0


def text_em_width(text: str, bold: bool = False) -> float:
    """Approximate width of *text* in em at the current font."""
    adv = _ADV_BOLD if bold else _ADV_REGULAR
    total = 0.0
    for ch in text:
        if ch.isdigit():
            total += adv["digit"]
        elif ch in ":.":
            total += adv["colon"]
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


def pct(value: float) -> str:
    """Format a percentage-of-canvas value for CSS."""
    return f"{value:.3f}%"


def em(value: float) -> str:
    return f"{value:.3f}em"


# ---------------------------------------------------------------------------
# Appearance styles
# ---------------------------------------------------------------------------

# Analog faces.  Lengths and thicknesses are percentages of the canvas; a hand
# is a bar whose bottom edge sits on the dial centre and which is rotated about
# the canvas centre, so ``*_len`` is measured from the centre outwards.
_ANALOG_BASE: Dict[str, Any] = {
    "dial_off": 1.0, "dial_size": 98.0,
    "dial_fill": "transparent", "dial_ring": "#3a3a48", "dial_ring_w": 2,
    "maj_w": 4.5, "maj_len": 8.5, "maj_top": 6.0, "maj_c": "#e8e8f2", "maj_r": 0,
    "mnr_w": 2.5, "mnr_len": 5.0, "mnr_top": 7.5, "mnr_c": "#5c5c6e", "mnr_r": 0,
    "hh_w": 5.5, "hh_len": 23.0, "hh_c": "#ffffff", "hh_r": 2,
    "mh_w": 4.0, "mh_len": 33.0, "mh_c": "#ffffff", "mh_r": 2,
    "sh_w": 2.0, "sh_len": 36.0, "sh_c": "#ff4b4b", "sh_r": 1,
    "st_len": 9.0,
    "hub_size": 7.0, "hub_c": "#ffffff", "hub_ring": "transparent", "hub_ring_w": 0,
    "num_c": "transparent", "num_em": 0.62, "num_inset": 11.0,
    "caption_c": "#8b8b9c", "accent": "#ff4b4b",
}

ANALOG_STYLES: Dict[str, Dict[str, Any]] = {
    "classic": {"_label": "Classic", "neutral": True},
    "minimal": {
        "_label": "Minimal",
        "dial_ring": "transparent", "maj_c": "transparent", "mnr_c": "transparent",
        "sh_c": "transparent", "st_len": 0.0, "hub_c": "#ffffff", "hub_size": 5.0,
        "hh_w": 4.5, "mh_w": 3.5, "hh_len": 22.0, "mh_len": 34.0, "hh_r": 3, "mh_r": 3,
    },
    "bauhaus": {
        "_label": "Bauhaus",
        "bg": "#f2efe6", "dial_ring": "transparent",
        "maj_c": "#1c1c1c", "maj_w": 6.5, "maj_len": 10.0, "mnr_c": "transparent",
        "hh_c": "#1c1c1c", "hh_w": 7.0, "mh_c": "#1c1c1c", "mh_w": 5.0,
        "sh_c": "#d8362a", "hub_c": "#d8362a", "hub_size": 8.5,
        "caption_c": "#5a5a5a", "accent": "#d8362a",
    },
    "railway": {
        "_label": "Railway",
        "bg": "#f6f6f6", "dial_ring": "#1a1a1a", "dial_ring_w": 2,
        "maj_c": "#1a1a1a", "maj_w": 5.0, "maj_len": 10.0,
        "mnr_c": "#1a1a1a", "mnr_w": 1.8, "mnr_len": 4.5,
        "hh_c": "#1a1a1a", "mh_c": "#1a1a1a",
        "sh_c": "#e2231a", "sh_w": 2.2, "sh_len": 30.0, "st_len": 10.0,
        "hub_c": "#e2231a", "hub_size": 10.0,
        "caption_c": "#555555", "accent": "#e2231a",
    },
    "chrono": {
        "_label": "Chronograph",
        "bg": "#0d0f14", "dial_ring": "#2a3040", "dial_ring_w": 3,
        "maj_c": "#d6dcea", "maj_w": 5.5, "mnr_c": "#404a60", "mnr_w": 3.0,
        "hh_w": 7.0, "hh_len": 22.0, "mh_w": 5.0, "mh_len": 32.0,
        "sh_c": "#ffb02e", "hub_c": "#ffb02e", "hub_size": 9.0,
        "caption_c": "#7d879c", "accent": "#ffb02e",
    },
    "neon": {
        "_label": "Neon",
        "bg": "#07030f", "dial_ring": "#8a2be2", "dial_ring_w": 2,
        "maj_c": "#00e5ff", "mnr_c": "#3b1d63",
        "hh_c": "#00e5ff", "mh_c": "#ff2bd6", "sh_c": "#ffe600",
        "hub_c": "#ffe600", "hub_size": 6.5,
        "caption_c": "#9d7bd8", "accent": "#ff2bd6",
    },
    "outline": {
        "_label": "Outline",
        "dial_ring": "#ffffff", "dial_ring_w": 1, "dial_off": 4.0, "dial_size": 92.0,
        "maj_c": "#ffffff", "maj_w": 1.8, "maj_len": 7.0, "maj_top": 9.0,
        "mnr_c": "transparent",
        "hh_w": 2.5, "mh_w": 2.0, "sh_c": "transparent", "st_len": 0.0,
        "hub_c": "transparent", "hub_ring": "#ffffff", "hub_ring_w": 1, "hub_size": 9.0,
        "caption_c": "#9a9aac", "accent": "#ffffff",
    },
    "numerals": {
        "_label": "Numerals",
        "dial_ring": "#33384a", "maj_c": "transparent",
        "mnr_c": "#3d4356", "mnr_w": 1.8, "mnr_len": 4.0, "mnr_top": 6.0,
        "num_c": "#e8e8f2", "num_em": 0.58, "num_inset": 13.0,
        "hh_len": 20.0, "mh_len": 29.0, "sh_len": 31.0,
        "sh_c": "#ff7a45", "hub_c": "#ff7a45", "accent": "#ff7a45",
    },
    "blueprint": {
        "_label": "Blueprint",
        "bg": "#0a1f3d", "dial_ring": "#2f6fb8", "dial_ring_w": 1,
        "maj_c": "#8fd0ff", "mnr_c": "#2f6fb8",
        "hh_c": "#d8efff", "mh_c": "#d8efff", "sh_c": "#7cffcb",
        "hub_c": "#7cffcb", "hub_size": 6.0,
        "caption_c": "#6ea8de", "accent": "#7cffcb",
    },
    "gold": {
        "_label": "Gold",
        "bg": "#0b0906", "dial_ring": "#8a6a2f", "dial_ring_w": 2,
        "maj_c": "#e8c877", "mnr_c": "#5c4a24",
        "hh_c": "#f3dda1", "mh_c": "#f3dda1", "sh_c": "#c9993f",
        "hub_c": "#e8c877", "hub_size": 6.5,
        "caption_c": "#a08a5a", "accent": "#e8c877",
    },
    "dots": {
        "_label": "Dots",
        "dial_ring": "transparent",
        "maj_c": "#ffffff", "maj_w": 6.0, "maj_len": 6.0, "maj_top": 6.5, "maj_r": 2,
        "mnr_c": "#585868", "mnr_w": 4.0, "mnr_len": 4.0, "mnr_top": 7.5, "mnr_r": 2,
        "sh_c": "#3ddc84", "hub_c": "#3ddc84", "hub_size": 6.0, "accent": "#3ddc84",
    },
    "halo": {
        "_label": "Halo",
        "bg": "#111018", "dial_ring": "#ff6a3d", "dial_ring_w": 3,
        "dial_off": 2.0, "dial_size": 96.0,
        "maj_c": "#ffffff", "maj_w": 3.0, "maj_len": 6.0, "maj_top": 10.0,
        "mnr_c": "transparent",
        "sh_c": "#ff6a3d", "hub_c": "#ff6a3d", "hub_size": 6.5,
        "caption_c": "#c2725a", "accent": "#ff6a3d",
    },
    "skeleton": {
        "_label": "Skeleton",
        "dial_ring": "transparent", "maj_c": "transparent", "mnr_c": "transparent",
        "hh_w": 3.5, "hh_len": 28.0, "mh_w": 2.5, "mh_len": 42.0,
        "sh_c": "#5ac8fa", "sh_w": 1.5, "sh_len": 43.0, "st_len": 12.0,
        "hub_c": "#5ac8fa", "hub_size": 5.0, "accent": "#5ac8fa",
    },
    "retro": {
        "_label": "Retro",
        "bg": "#efe3c8", "dial_ring": "#8b6b3f", "dial_ring_w": 2,
        "maj_c": "#3a2c1a", "mnr_c": "#a08a63",
        "hh_c": "#3a2c1a", "mh_c": "#3a2c1a", "sh_c": "#b4442e",
        "hub_c": "#3a2c1a", "hub_size": 8.0,
        "caption_c": "#6b5537", "accent": "#b4442e",
    },
    "aviator": {
        "_label": "Aviator",
        "bg": "#14161a", "dial_ring": "#ff8a00", "dial_ring_w": 2,
        "dial_off": 2.0, "dial_size": 96.0,
        "maj_c": "#ff8a00", "maj_w": 4.0, "maj_len": 8.0,
        "mnr_c": "#4a4238", "mnr_w": 2.5, "mnr_len": 5.0,
        "hh_c": "#f5f1e8", "mh_c": "#f5f1e8", "sh_c": "#ff8a00",
        "hub_c": "#ff8a00", "hub_size": 7.5,
        "caption_c": "#9a8f7d", "accent": "#ff8a00",
    },
    "midnight": {
        "_label": "Midnight",
        "bg": "#05060c", "dial_ring": "#1b2240", "dial_ring_w": 6,
        "dial_off": 4.0, "dial_size": 92.0,
        "maj_c": "#5b6bff", "maj_w": 4.0, "mnr_c": "transparent",
        "hh_c": "#c8ceff", "mh_c": "#c8ceff", "sh_c": "#5b6bff",
        "hub_c": "#c8ceff", "hub_size": 6.0,
        "caption_c": "#5a63a0", "accent": "#5b6bff",
    },
}

# Digital faces.  ``tmpl`` selects the markup; everything else is colour and
# type treatment plus the optional card / rule decorations.
_DIGITAL_BASE: Dict[str, Any] = {
    "bg": "#0b0b10",
    "fg": "#ffffff",
    "dim": "#7d7d90",
    "accent": "#4c8dff",
    "wt": "bold",
    "ff": "DejaVu Sans",
    "cap_em": 1.75,
    "upper": False,
    "tmpl": "digital",
    "card": None,     # (x, y, w, h, fill, radius, border_w, border_c)
    "bar": None,      # (x, y, w, h, fill, radius)
    "stack": False,
    "badge": False,   # AM/PM as a filled pill in the top-right corner
    "tile_fill": "#1a1c26",
    "tile_accent": "#4c8dff",
}

DIGITAL_STYLES: Dict[str, Dict[str, Any]] = {
    "classic": {"_label": "Classic", "neutral": True},
    "bold": {
        "_label": "Bold", "bg": "#000000", "fg": "#ffffff", "dim": "#8a8a8a",
        "accent": "#ffffff", "cap_em": 2.0,
    },
    "light": {
        "_label": "Light", "bg": "#f4f4f7", "fg": "#16161c", "dim": "#71717f",
        "accent": "#2f6fed", "wt": "normal",
    },
    "mono": {
        "_label": "Mono", "bg": "#101014", "fg": "#e6e6ee", "dim": "#6b6b7c",
        "accent": "#e6e6ee", "ff": "DejaVu Sans Mono", "wt": "normal",
    },
    "lcd": {
        "_label": "LCD", "bg": "#0d1a12", "fg": "#7dffb0", "dim": "#2f6b48",
        "accent": "#7dffb0", "ff": "DejaVu Sans Mono",
        "card": (4.0, 4.0, 92.0, 92.0, "#08120c", 6, 1, "#1e4630"),
    },
    "tiles": {
        "_label": "Tiles", "bg": "#05070c", "fg": "#ffffff", "dim": "#6b7080",
        "accent": "#3d7bff", "tmpl": "digital_boxed",
        "tile_fill": "#151a26", "tile_accent": "#3d7bff",
    },
    "neon": {
        "_label": "Neon", "bg": "#0a0416", "fg": "#00e5ff", "dim": "#7a45c9",
        "accent": "#ff2bd6",
        "bar": (16.0, 78.0, 68.0, 2.0, "#ff2bd6", 1),
    },
    "terminal": {
        "_label": "Terminal", "bg": "#04120a", "fg": "#33ff66", "dim": "#1f8a42",
        "accent": "#33ff66", "ff": "DejaVu Sans Mono", "wt": "normal",
        "upper": True,
    },
    "card": {
        "_label": "Card", "bg": "#15161c", "fg": "#ffffff", "dim": "#8c8ca0",
        "accent": "#ff9f0a",
        "card": (6.0, 8.0, 88.0, 84.0, "#20222c", 8, 0, "transparent"),
        "bar": (6.0, 8.0, 88.0, 4.0, "#ff9f0a", 2),
    },
    "stacked": {
        "_label": "Stacked", "bg": "#0b0b10", "fg": "#ffffff", "dim": "#7d7d90",
        "accent": "#ff375f", "stack": True, "cap_em": 1.6,
    },
    "headline": {
        "_label": "Headline", "bg": "#1b1d24", "fg": "#ffffff", "dim": "#9aa0b4",
        "accent": "#00d1b2", "cap_em": 2.1,
        "bar": (0.0, 0.0, 100.0, 5.0, "#00d1b2", 0),
    },
    "ticker": {
        "_label": "Ticker", "bg": "#101218", "fg": "#f5c542", "dim": "#8b8f9c",
        "accent": "#f5c542", "ff": "DejaVu Sans Mono",
        "bar": (0.0, 95.0, 100.0, 5.0, "#f5c542", 0),
    },
    "outline": {
        "_label": "Outline", "bg": "#0e0e12", "fg": "#ffffff", "dim": "#8a8a9c",
        "accent": "#ffffff", "wt": "normal",
        "card": (5.0, 5.0, 90.0, 90.0, "transparent", 10, 1, "#43435a"),
    },
    "sunrise": {
        "_label": "Sunrise", "bg": "linear-gradient(160deg, #ff7a45, #ff2e63)",
        "fg": "#ffffff", "dim": "#ffd9cc", "accent": "#ffffff",
    },
    "minimal": {
        "_label": "Minimal", "bg": "#000000", "fg": "#ffffff", "dim": "#5c5c66",
        "accent": "#ffffff", "wt": "normal", "cap_em": 1.6,
    },
    "badge": {
        "_label": "Badge", "bg": "#0b0f1a", "fg": "#ffffff", "dim": "#7a86a0",
        "accent": "#2f6fed", "badge": True,
    },
}


def analog_style(key: str) -> Dict[str, Any]:
    merged = dict(_ANALOG_BASE)
    merged["bg"] = "#101016"
    merged.update(ANALOG_STYLES.get(key) or ANALOG_STYLES["classic"])
    return merged


def digital_style(key: str) -> Dict[str, Any]:
    merged = dict(_DIGITAL_BASE)
    merged.update(DIGITAL_STYLES.get(key) or DIGITAL_STYLES["classic"])
    return merged


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------

DATE_FORMATS: Dict[str, str] = {
    "auto": "%b %d",
    "md": "%m/%d/%y",
    "dm": "%d/%m/%y",
    "dot": "%d.%m.%y",
    "iso": "%Y-%m-%d",
    "long": "%b %d, %Y",
}


def format_time(now: datetime, cfg: Dict[str, Any]) -> Tuple[str, str]:
    """Return ``(time_text, am_pm_text)`` for *now* under the button's config."""
    custom = str(cfg.get("custom_format") or "").strip()
    if custom:
        try:
            return now.strftime(custom), ""
        except ValueError:
            pass

    if "hour_format" in cfg:
        twelve = str(cfg.get("hour_format")) == "12"
    else:
        twelve = bool(cfg.get("hour_12", False))
    seconds = bool(cfg.get("show_seconds", False))

    if twelve:
        hour = now.hour % 12 or 12
        text = f"{hour}:{now.minute:02d}"
        if seconds:
            text += f":{now.second:02d}"
        return text, "AM" if now.hour < 12 else "PM"

    text = f"{now.hour:02d}:{now.minute:02d}"
    if seconds:
        text += f":{now.second:02d}"
    return text, ""


def format_date(now: datetime, cfg: Dict[str, Any]) -> str:
    """Return the date caption, including the weekday when it is enabled."""
    parts: List[str] = []
    if cfg.get("show_weekday", False):
        parts.append(now.strftime("%A" if cfg.get("long_weekday", False) else "%a"))
    if cfg.get("show_date", False):
        parts.append(now.strftime(DATE_FORMATS.get(str(cfg.get("date_format", "auto")), "%b %d")))
    return " ".join(parts)


def hand_angles(now: datetime, sweep: bool = False) -> Tuple[float, float, float]:
    """Return ``(hour, minute, second)`` hand angles in degrees clockwise from 12."""
    second = now.second + (now.microsecond / 1_000_000.0 if sweep else 0.0)
    minute = now.minute + second / 60.0
    hour = (now.hour % 12) + minute / 60.0
    return hour * 30.0, minute * 6.0, second * 6.0


# ---------------------------------------------------------------------------
# Colour overrides
# ---------------------------------------------------------------------------

# How far an ink has to sit from the background, in perceived brightness, to
# still read on a 72 px key.  Deliberately low: a dial ring or a minute tick is
# meant to be quiet, and rescuing those would make a black button look louder
# than the theme it is based on.
_MIN_INK_DELTA = 0.20

# Ink roles and their substitutes as (on a dark background, on a light one).
# Used only when a colour lands too close to the background to be legible.
_INK_SUBSTITUTES: Dict[str, Tuple[str, str]] = {
    "fg": ("#ffffff", "#15151b"),
    "hh_c": ("#ffffff", "#15151b"),
    "mh_c": ("#ffffff", "#15151b"),
    "dg_c": ("#ffffff", "#15151b"),
    "maj_c": ("#e8e8f2", "#1d1d26"),
    "num_c": ("#e8e8f2", "#1d1d26"),
    "dim": ("#b9b9c6", "#4a4a55"),
    "caption_c": ("#b9b9c6", "#4a4a55"),
    "mnr_c": ("#9a9aa8", "#6a6a76"),
    "dial_ring": ("#8f8f9e", "#6a6a76"),
}
_ACCENT_INK = ("accent", "sh_c", "hub_c", "tile_accent")
_PRIMARY_INK = ("fg", "hh_c", "mh_c", "maj_c", "dg_c")

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
    return "#" + "".join(
        f"{int(c + (target - c) * amount):02x}" for c in rgb
    )


def relight(style: Dict[str, Any], background: str) -> None:
    """Rescue any ink that would vanish against *background*.

    Called only when the background comes from the button rather than the
    theme, so a theme that ships its own light palette (Railway, Retro) keeps
    the ink its author chose. Colours that already contrast are left untouched,
    which is why a black button still renders the stock Classic face.
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

    for key in _ACCENT_INK:
        ink = luminance(style.get(key))
        if ink is None or abs(ink - bg_lum) >= _MIN_INK_DELTA:
            continue
        style[key] = _shade(style[key], to_dark=light_bg)

    # Tiles are a surface, not ink: lift them off the background instead of
    # swapping them for a fixed colour.
    tile = luminance(style.get("tile_c"))
    if tile is not None and abs(tile - bg_lum) < 0.14:
        style["tile_c"] = _shade(background, to_dark=light_bg, amount=0.22)


def apply_colors(style: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fold the button's colour settings into *style*, in place.

    ``"style"`` keeps the face's own palette, except for the themes marked
    ``neutral`` -- Classic has no palette of its own, so it follows the button's
    colour or gradient and the colour picker in the editor does something.
    ``"button"`` opts any other theme into the same behaviour, and ``"custom"``
    takes the three hex fields from the property panel.
    """
    source = str(cfg.get("color_source", "style"))
    if source == "style" and style.get("neutral"):
        source = "button"

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
            relight(style, bg)
        if fg:
            for key in (*_PRIMARY_INK, "num_c"):
                if key in style and style[key] != "transparent":
                    style[key] = fg
        if accent:
            for key in _ACCENT_INK:
                if key in style and style[key] != "transparent":
                    style[key] = accent
    return style


# ---------------------------------------------------------------------------
# State builders
# ---------------------------------------------------------------------------

# Every name the stylesheet interpolates, at a value that draws nothing.  A
# face fills in only the keys it uses, so anything belonging to another
# template resolves to a no-op instead of a stray literal in the CSS.
_CSS_DEFAULTS: Dict[str, Any] = {
    "bar_c": "transparent",
    "bar_h": "0",
    "bar_r": "0",
    "bar_w": "0",
    "bar_x": "0",
    "bar_y": "0",
    "bg": "transparent",
    "card_bc": "transparent",
    "card_bw": "0",
    "card_c": "transparent",
    "card_h": "0",
    "card_r": "0",
    "card_w": "0",
    "card_x": "0",
    "card_y": "0",
    "col_h": "0",
    "col_y": "0",
    "colon_c": "transparent",
    "colon_size": "0.7em",
    "colon_w": "0",
    "colon_x": "0",
    "colon_y": "0",
    "dg_c": "transparent",
    "dg_size": "0.7em",
    "dg_y": "0",
    "dial_fill": "transparent",
    "dial_off": "0",
    "dial_ring": "transparent",
    "dial_ring_w": "0",
    "dial_size": "0.7em",
    "hh_c": "transparent",
    "hh_deg": "0",
    "hh_h": "0",
    "hh_r": "0",
    "hh_w": "0",
    "hh_x": "0",
    "hh_y": "0",
    "hub_c": "transparent",
    "hub_ring": "transparent",
    "hub_ring_w": "0",
    "hub_size": "0.7em",
    "hub_x": "0",
    "maj_c": "transparent",
    "maj_h": "0",
    "maj_r": "0",
    "maj_w": "0",
    "maj_x": "0",
    "maj_y": "0",
    "mh_c": "transparent",
    "mh_deg": "0",
    "mh_h": "0",
    "mh_r": "0",
    "mh_w": "0",
    "mh_x": "0",
    "mh_y": "0",
    "mnr_c": "transparent",
    "mnr_h": "0",
    "mnr_r": "0",
    "mnr_w": "0",
    "mnr_x": "0",
    "mnr_y": "0",
    "num_c": "transparent",
    "num_edge": "0",
    "num_side": "0",
    "num_size": "0.7em",
    "pg_fill": "transparent",
    "pg_fw": "0",
    "pg_h": "0",
    "pg_r": "0",
    "pg_track": "transparent",
    "pg_w": "0",
    "pg_x": "0",
    "pg_y": "0",
    "sh_c": "transparent",
    "sh_deg": "0",
    "sh_h": "0",
    "sh_r": "0",
    "sh_w": "0",
    "sh_x": "0",
    "sh_y": "0",
    "st_h": "0",
    "st_y": "0",
    "tile1_x": "0",
    "tile2_x": "0",
    "tile3_x": "0",
    "tile4_x": "0",
    "tile_c": "transparent",
    "tile_h": "0",
    "tile_hi": "transparent",
    "tile_r": "0",
    "tile_w": "0",
    "tile_y": "0",
}


_SLOTS = (1, 2, 3, 4, 5)


def blank_slots() -> Dict[str, Any]:
    """A neutral state: every stylesheet name present, every text slot empty."""
    out: Dict[str, Any] = dict(_CSS_DEFAULTS)
    for n in _SLOTS:
        out.update({
            f"s{n}_t": "",
            f"s{n}_c": "#ffffff",
            f"s{n}_size": "0.7em",
            f"s{n}_wt": "normal",
            f"s{n}_ff": "DejaVu Sans",
            f"s{n}_al": "center",
            f"s{n}_pt": "0",
            f"s{n}_x": "0%",
            f"s{n}_y": "50%",
            f"s{n}_w": "100%",
        })
    return out


def slot(n: int, text: str, color: str, size_em: float, **kw: Any) -> Dict[str, Any]:
    """Fill text slot *n*.  Flow slots (1-4) use ``pad_top``; slot 5 is absolute."""
    out = {
        f"s{n}_t": text,
        f"s{n}_c": color,
        f"s{n}_size": em(size_em),
        f"s{n}_wt": kw.get("weight", "normal"),
        f"s{n}_ff": kw.get("family", "DejaVu Sans"),
        f"s{n}_al": kw.get("align", "center"),
        f"s{n}_pt": str(kw.get("pad_top", 0)),
    }
    if "x" in kw:
        out[f"s{n}_x"] = pct(kw["x"])
    if "y" in kw:
        out[f"s{n}_y"] = pct(kw["y"])
    if "w" in kw:
        out[f"s{n}_w"] = pct(kw["w"])
    return out


def decorations(style: Dict[str, Any]) -> Dict[str, Any]:
    """Card and rule geometry, collapsed to invisible when the style has none."""
    card = style.get("card")
    bar = style.get("bar")
    out: Dict[str, Any] = {}
    if card:
        x, y, w, h, fill, radius, bw, bc = card
        out.update({
            "card_x": pct(x), "card_y": pct(y), "card_w": pct(w), "card_h": pct(h),
            "card_c": fill, "card_r": str(radius), "card_bw": str(bw), "card_bc": bc,
        })
    else:
        out.update({
            "card_x": "0%", "card_y": "0%", "card_w": "0%", "card_h": "0%",
            "card_c": "transparent", "card_r": "0", "card_bw": "0",
            "card_bc": "transparent",
        })
    if bar:
        x, y, w, h, fill, radius = bar
        out.update({
            "bar_x": pct(x), "bar_y": pct(y), "bar_w": pct(w), "bar_h": pct(h),
            "bar_c": fill, "bar_r": str(radius),
        })
    else:
        out.update({
            "bar_x": "0%", "bar_y": "0%", "bar_w": "0%", "bar_h": "0%",
            "bar_c": "transparent", "bar_r": "0",
        })
    return out


def analog_state(
    now: datetime,
    cfg: Dict[str, Any],
    *,
    caption: str = "",
    sweep: bool = False,
) -> Dict[str, Any]:
    """Build the render state for an analog face."""
    style = apply_colors(analog_style(str(cfg.get("analog_style", "classic"))), cfg)
    hour_deg, min_deg, sec_deg = hand_angles(now, sweep)

    if not cfg.get("show_second_hand", True):
        style["sh_c"] = "transparent"
        style["st_len"] = 0.0

    numerals = style["num_c"] != "transparent"
    state: Dict[str, Any] = blank_slots()
    state.update(decorations({"card": None, "bar": None}))
    state.update({
        "_template": "analog",
        "bg": style["bg"],
        "dial_off": pct(style["dial_off"]),
        "dial_size": pct(style["dial_size"]),
        "dial_fill": style["dial_fill"],
        "dial_ring": style["dial_ring"],
        "dial_ring_w": str(style["dial_ring_w"]),

        "maj_x": pct((100.0 - style["maj_w"]) / 2.0),
        "maj_y": pct(style["maj_top"]),
        "maj_w": pct(style["maj_w"]),
        "maj_h": pct(style["maj_len"]),
        "maj_c": style["maj_c"],
        "maj_r": str(style["maj_r"]),

        "mnr_x": pct((100.0 - style["mnr_w"]) / 2.0),
        "mnr_y": pct(style["mnr_top"]),
        "mnr_w": pct(style["mnr_w"]),
        "mnr_h": pct(style["mnr_len"]),
        "mnr_c": style["mnr_c"],
        "mnr_r": str(style["mnr_r"]),

        "hh_x": pct((100.0 - style["hh_w"]) / 2.0),
        "hh_y": pct(50.0 - style["hh_len"]),
        "hh_w": pct(style["hh_w"]),
        "hh_h": pct(style["hh_len"]),
        "hh_c": style["hh_c"],
        "hh_r": str(style["hh_r"]),
        "hh_deg": f"{hour_deg:.3f}",

        "mh_x": pct((100.0 - style["mh_w"]) / 2.0),
        "mh_y": pct(50.0 - style["mh_len"]),
        "mh_w": pct(style["mh_w"]),
        "mh_h": pct(style["mh_len"]),
        "mh_c": style["mh_c"],
        "mh_r": str(style["mh_r"]),
        "mh_deg": f"{min_deg:.3f}",

        "sh_x": pct((100.0 - style["sh_w"]) / 2.0),
        "sh_y": pct(50.0 - style["sh_len"]),
        "sh_w": pct(style["sh_w"]),
        "sh_h": pct(style["sh_len"]),
        "sh_c": style["sh_c"],
        "sh_r": str(style["sh_r"]),
        "sh_deg": f"{sec_deg:.3f}",

        "st_y": "50%",
        "st_h": pct(style["st_len"]),

        "hub_x": pct((100.0 - style["hub_size"]) / 2.0),
        "hub_size": pct(style["hub_size"]),
        "hub_c": style["hub_c"],
        "hub_ring": style["hub_ring"],
        "hub_ring_w": str(style["hub_ring_w"]),

        "num_c": style["num_c"],
        "num_size": em(style["num_em"]),
        "num_edge": pct(style["num_inset"]),
        "num_side": pct(style["num_inset"] + 2.0),
        "n12_t": "12" if numerals else "",
        "n3_t": "3" if numerals else "",
        "n6_t": "6" if numerals else "",
        "n9_t": "9" if numerals else "",
    })

    # Slot 1: AM/PM above the dial centre.  Slot 2: caption below it.
    _, ampm = format_time(now, cfg)
    if ampm and not numerals:
        state.update(slot(1, ampm, style["accent"], 0.52, weight="bold", y=30.0))
    date_text = format_date(now, cfg)
    if caption and date_text:
        state.update(slot(2, caption, style["caption_c"], 0.5, y=71.0))
        state.update(slot(3, date_text, style["caption_c"], 0.45, y=82.0))
    elif caption:
        state.update(slot(2, caption, style["caption_c"], 0.55, y=74.0))
    elif date_text:
        state.update(slot(2, date_text, style["caption_c"], 0.5, y=74.0))
    return state


def digital_state(
    now: datetime,
    cfg: Dict[str, Any],
    *,
    caption: str = "",
) -> Dict[str, Any]:
    """Build the render state for a digital face."""
    style = apply_colors(digital_style(str(cfg.get("digital_style", "classic"))), cfg)
    time_text, ampm = format_time(now, cfg)
    date_text = format_date(now, cfg)
    if style["upper"]:
        caption = caption.upper()
        date_text = date_text.upper()

    state: Dict[str, Any] = blank_slots()
    state.update(decorations(style))
    state.update({
        "_template": style["tmpl"],
        "bg": style["bg"],
        "col_y": "0%",
        "col_h": "100%",
    })

    if style["tmpl"] == "digital_boxed":
        state.update(_boxed_state(time_text, ampm, caption, date_text, style))
        return state

    bold = style["wt"] == "bold"
    # Mono faces run wider than the DejaVu Sans metrics the fitter assumes.
    width_budget = 80.0

    n = 1
    if caption:
        state.update(slot(n, caption, style["dim"],
                          fit_em(caption, 88.0, 0.62), family=style["ff"]))
        n += 1

    # A stacked or badged face keeps AM/PM out of the big row; everything
    # else puts it inline.
    corner_ampm = bool(ampm) and (style["badge"] or style["stack"])
    shown = time_text if corner_ampm or not ampm else f"{time_text} {ampm}"

    if style["stack"] and ":" in time_text:
        head, _, tail = time_text.partition(":")
        for i, part in enumerate((head, tail)):
            state.update(slot(n, part, style["fg"],
                              fit_em(part, 56.0, style["cap_em"], bold),
                              weight=style["wt"], family=style["ff"],
                              pad_top=6 if i else 0))
            n += 1
    else:
        state.update(slot(n, shown, style["fg"],
                          fit_em(shown, width_budget, style["cap_em"], bold),
                          weight=style["wt"], family=style["ff"],
                          pad_top=2 if n > 1 else 0))
        n += 1

    if date_text and n <= 4:
        state.update(slot(n, date_text, style["dim"],
                          fit_em(date_text, 90.0, 0.6), family=style["ff"], pad_top=3))

    if corner_ampm:
        state.update(slot(5, ampm, style["accent"], 0.5, weight="bold",
                          x=58.0, y=13.0, w=38.0, align="right"))
    return state


def _boxed_state(
    time_text: str, ampm: str, caption: str, date_text: str, style: Dict[str, Any],
) -> Dict[str, Any]:
    """Tile layout: one rounded tile per digit, with the colon between them."""
    # Take hours and minutes as separate fields: a 12-hour "8:04" has to become
    # 08 04, not the first four digits of the string.
    parts = time_text.split(":")
    hours = (parts[0] if parts else "0").rjust(2, "0")[-2:]
    minutes = (parts[1] if len(parts) > 1 else "00").rjust(2, "0")[:2]
    digits = list(hours + minutes)

    tile_w, gap, colon_w = 19.0, 2.0, 8.0
    total = tile_w * 4 + gap * 4 + colon_w
    left = (100.0 - total) / 2.0
    xs = [
        left,
        left + tile_w + gap,
        left + (tile_w + gap) * 2 + colon_w + gap,
        left + (tile_w + gap) * 3 + colon_w + gap,
    ]
    top, height = 32.0, 32.0

    out: Dict[str, Any] = {
        "tile_y": pct(top), "tile_h": pct(height), "tile_w": pct(tile_w),
        "tile_r": "3",
        "tile_c": style["tile_fill"],
        "tile_hi": style["tile_accent"],
        "dg_c": style["fg"],
        "dg_size": em(1.05),
        "dg_y": pct(top + height / 2.0),
        "colon_t": ":",
        "colon_c": style["accent"],
        "colon_x": pct(left + (tile_w + gap) * 2),
        "colon_w": pct(colon_w),
        "colon_y": pct(top + height / 2.0),
        "colon_size": em(0.9),
    }
    for i, (x, digit) in enumerate(zip(xs, digits), start=1):
        out[f"tile{i}_x"] = pct(x)
        out[f"dg{i}_t"] = digit
    out.update(slot(1, caption, style["dim"], 0.55, x=0.0, y=16.0, w=100.0))
    bottom = " ".join(p for p in (date_text, ampm) if p)
    out.update(slot(2, bottom, style["dim"], 0.5, x=0.0, y=83.0, w=100.0))
    return out


def countdown_state(
    remaining: float,
    total: float,
    cfg: Dict[str, Any],
    *,
    caption: str,
    running: bool,
    paused: bool = False,
) -> Dict[str, Any]:
    """Build the render state for the countdown face."""
    style = apply_colors(digital_style(str(cfg.get("digital_style", "classic"))), cfg)
    done = remaining <= 0
    countup = done and str(cfg.get("on_finish", "zero")) == "countup"

    span = -remaining if countup else max(0.0, remaining)
    seconds = int(span) if countup else int(span + 0.999)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        text = f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        text = f"{minutes}:{secs:02d}"
    if countup:
        text = f"+{text}"

    color = style["accent"] if done else style["fg"]
    progress = 0.0 if total <= 0 else max(0.0, min(100.0, remaining / total * 100.0))

    state: Dict[str, Any] = blank_slots()
    state.update(decorations(style))
    state.update({
        "_template": "countdown",
        "bg": style["bg"],
        "col_y": "0%",
        "col_h": "84%",
        "pg_x": pct(12.0), "pg_y": pct(85.0), "pg_w": pct(76.0), "pg_h": "4",
        "pg_fw": pct(76.0 * progress / 100.0),
        "pg_r": "2",
        "pg_track": style["dim"],
        "pg_fill": style["accent"],
    })
    state.update(slot(1, caption, style["dim"], fit_em(caption, 88.0, 0.6),
                      family=style["ff"]))
    state.update(slot(2, text, color,
                      fit_em(text, 84.0, style["cap_em"], style["wt"] == "bold"),
                      weight=style["wt"], family=style["ff"], pad_top=2))
    status = "" if not done else ("" if countup else "DONE")
    if not done and paused:
        status = "PAUSED"
    if status:
        state.update(slot(3, status, style["accent"], 0.5, weight="bold", pad_top=3))
    return state
