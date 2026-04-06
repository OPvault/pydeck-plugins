"""Home Assistant REST API client and MDI icon renderer for PyDeck.

Handles entity state queries, service calls, icon fetching, and SVG
rasterization.  Icons are sourced from the MDI CDN and optionally
rasterized with cairosvg; a full Pillow fallback set is included for
environments without cairo.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw

_ICON_CDN = "https://cdn.jsdelivr.net/npm/@mdi/svg@7.4.47/svg/{}.svg"
_svg_cache: dict[str, Optional[bytes]] = {}
_pil_cache: dict[tuple, Image.Image] = {}

try:
    import cairosvg as _cairosvg

    _HAS_CAIROSVG = True
except ImportError:
    _HAS_CAIROSVG = False

_PLUGIN_DIR = Path(__file__).parent
# Runtime-generated icons go to plugins/storage/ (survives plugin updates).
# _PLUGIN_DIR.parents[1] == pydeck/plugins/
_STORAGE_DIR = _PLUGIN_DIR.parents[1] / "storage" / "home-assistant"

BUTTON_SIZE = 80

_DOMAIN_ICONS: dict[str, tuple[str, str]] = {
    "switch": ("toggle-switch", "toggle-switch-off"),
    "light": ("lightbulb", "lightbulb-outline"),
    "input_boolean": ("toggle-switch", "toggle-switch-off"),
    "automation": ("robot", "robot"),
    "binary_sensor": ("eye", "eye-off"),
    "media_player": ("speaker", "speaker-off"),
    "climate": ("thermostat", "thermostat"),
    "cover": ("garage-open", "garage"),
    "fan": ("fan", "fan-off"),
    "lock": ("lock-open", "lock"),
    "script": ("script-text", "script-text"),
    "scene": ("palette", "palette"),
}

_DEVICE_CLASS_ICONS: dict[str, str] = {
    "temperature": "thermometer",
    "humidity": "water-percent",
    "pressure": "gauge",
    "power": "flash",
    "energy": "lightning-bolt",
    "current": "current-ac",
    "voltage": "sine-wave",
    "battery": "battery",
    "illuminance": "brightness-5",
    "carbon_dioxide": "molecule-co2",
    "carbon_monoxide": "molecule-co",
    "pm25": "air-filter",
    "pm10": "air-filter",
    "motion": "motion-sensor",
    "door": "door",
    "window": "window-open",
    "moisture": "water",
    "gas": "fire",
    "smoke": "smoke-detector",
    "speed": "speedometer",
    "wind_speed": "weather-windy",
}


# ── Custom exception ──────────────────────────────────────────────────────────


class HaClientError(Exception):
    """Raised for Home Assistant API errors with user-friendly messages."""


# ── HA REST client ────────────────────────────────────────────────────────────


class HaClient:
    """Minimal Home Assistant REST API client."""

    def __init__(self, url: str, token: str):
        url = url.rstrip("/")
        parsed = urllib.parse.urlparse(url)
        if not parsed.port:
            url = f"{parsed.scheme}://{parsed.hostname}:8123{parsed.path or ''}"
        self.url = url
        self.token = token

    def _request(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise HaClientError(
                    "401 Unauthorized — check your Long-Lived Access Token"
                ) from e
            if e.code == 404:
                raise HaClientError(
                    f"404 Not Found — check your Home Assistant URL ({self.url})"
                ) from e
            raise HaClientError(f"HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise HaClientError(
                f"Connection failed — check your Home Assistant URL ({self.url}): {e.reason}"
            ) from e

    def get_state(self, entity_id: str) -> dict:
        return self._request("GET", f"/api/states/{entity_id}")

    def call_service(self, domain: str, service: str, entity_id: str) -> Any:
        return self._request(
            "POST",
            f"/api/services/{domain}/{service}",
            {"entity_id": entity_id},
        )

    def toggle(self, entity_id: str) -> Any:
        return self.call_service("homeassistant", "toggle", entity_id)

    def list_states(self) -> list:
        return self._request("GET", "/api/states")

    def test_connection(self) -> bool:
        try:
            self._request("GET", "/api/")
            return True
        except Exception:
            return False


# ── Icon helpers ──────────────────────────────────────────────────────────────


def _normalize_icon_name(icon_name: str) -> str:
    """Strip the 'mdi:' prefix and normalise colons to dashes.

    Ensures cache keys are consistent regardless of whether the caller
    passes 'mdi:lightbulb' or 'lightbulb'.
    """
    return icon_name.removeprefix("mdi:").replace(":", "-")


def default_icon(
    entity_id: str, state: str, device_class: str = ""
) -> str:
    """Return the appropriate MDI icon name for a given entity."""
    if device_class and device_class in _DEVICE_CLASS_ICONS:
        return _DEVICE_CLASS_ICONS[device_class]
    domain = entity_id.split(".")[0]
    is_on = (state or "").lower() == "on"
    pair = _DOMAIN_ICONS.get(domain, ("home-automation", "home-automation"))
    return pair[0] if is_on else pair[1]


def fetch_icon_svg(icon_name: str) -> Optional[bytes]:
    """Fetch an MDI SVG from CDN, caching results in memory."""
    key = _normalize_icon_name(icon_name)
    if key in _svg_cache:
        return _svg_cache[key]
    try:
        req = urllib.request.Request(
            _ICON_CDN.format(key),
            headers={"User-Agent": "pydeck/2.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            svg = resp.read()
        _svg_cache[key] = svg
        return svg
    except Exception:
        _svg_cache[key] = None
        return None


def _hex_to_rgba(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def _contrasting_color(hex_bg: str) -> str:
    """Return white or black hex depending on background luminance."""
    r, g, b, _ = _hex_to_rgba(hex_bg)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "#ffffff" if lum < 140 else "#000000"


def svg_to_pil(
    svg_bytes: Optional[bytes],
    size: int = 36,
    hex_color: str = "#ffffff",
    icon_name: str = "",
) -> Optional[Image.Image]:
    """Rasterize an SVG to a PIL RGBA Image, tinted with *hex_color*.

    Uses cairosvg when available; otherwise a Pillow fallback shape.
    """
    # Normalize the name so cache keys are always consistent.
    norm_name = _normalize_icon_name(icon_name) if icon_name else "__fallback__"
    cache_key = (norm_name, hex_color, size)
    cached = _pil_cache.get(cache_key)
    if cached is not None:
        return cached.copy()

    rgba_color = _hex_to_rgba(hex_color)
    result: Optional[Image.Image] = None

    if svg_bytes is not None and _HAS_CAIROSVG:
        try:
            svg_str = svg_bytes.decode("utf-8")
            svg_str = svg_str.replace("<svg ", f'<svg fill="{hex_color}" ')
            png = _cairosvg.svg2png(
                bytestring=svg_str.encode(),
                output_width=size,
                output_height=size,
            )
            result = Image.open(io.BytesIO(png)).convert("RGBA")
        except Exception:
            pass

    if result is None:
        result = _draw_fallback_icon(size, rgba_color, icon_name)

    _pil_cache[cache_key] = result
    return result.copy()


def render_entity_icon(
    icon_name: str,
    size: int = BUTTON_SIZE,
    is_on: bool = False,
) -> Optional[str]:
    """Render an MDI icon as a transparent PNG (icon only, no text).

    When *is_on* is True the icon is tinted warm yellow; otherwise white.
    Transparent background so the button's configured colour shows through.
    The icon is vertically centred in the upper portion, leaving a bottom
    margin for Title.

    Returns the relative path from the project root (suitable for
    ``display_update.image``), or ``None`` if rendering fails.
    """
    try:
        norm_name = _normalize_icon_name(icon_name)
        icon_color = "#fff3b0" if is_on else "#ffffff"
        cache_hash = hashlib.md5(
            f"{norm_name}:{size}:{icon_color}".encode()
        ).hexdigest()[:12]
        filename = f"_icon_{cache_hash}.png"
        rel_path = f"plugins/storage/home-assistant/{filename}"
        abs_path = _STORAGE_DIR / filename

        if abs_path.exists():
            return rel_path

        bottom_margin = 20
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        icon_size = int(size * 0.55)

        svg = fetch_icon_svg(norm_name)
        icon_img = svg_to_pil(
            svg, size=icon_size, hex_color=icon_color, icon_name=norm_name
        )
        if icon_img:
            usable_h = size - bottom_margin
            offset_x = (size - icon_img.width) // 2
            offset_y = max(0, (usable_h - icon_img.height) // 2)
            img.paste(icon_img, (offset_x, offset_y), icon_img)

        _STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        img.save(str(abs_path), format="PNG")
        return rel_path
    except Exception:
        return None


# ── Pillow fallback icons ─────────────────────────────────────────────────────


def _draw_fallback_icon(
    size: int, color: tuple, icon_name: str = ""
) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    n = icon_name.lower()
    lw = max(2, size // 14)

    if "toggle-switch" in n:
        _fb_toggle(draw, size, color, lw, is_on="off" not in n)
    elif "lightbulb" in n or "brightness" in n or "sun" in n or "illumin" in n:
        _fb_bulb(draw, size, color, lw, outline_only="outline" in n or "brightness" in n)
    elif "eye" in n:
        _fb_eye(draw, size, color, lw, open_="off" not in n)
    elif "lock" in n:
        _fb_lock(draw, size, color, lw, unlocked="open" in n)
    elif "fan" in n:
        _fb_fan(draw, size, color, lw)
    elif "home" in n:
        _fb_house(draw, size, color, lw)
    elif "thermosta" in n or "thermometer" in n:
        _fb_thermo(draw, size, color, lw)
    elif "speaker" in n:
        _fb_speaker(draw, size, color, lw, muted="off" in n)
    elif "folder" in n:
        _fb_folder(draw, size, color, lw)
    elif "arrow-left" in n or "return" in n:
        _fb_arrow_left(draw, size, color, lw)
    elif "water" in n or "drop" in n or "moisture" in n or "humid" in n:
        _fb_water_drop(draw, size, color, lw)
    elif "flash" in n or "lightning" in n or "bolt" in n:
        _fb_lightning(draw, size, color, lw)
    elif "battery" in n:
        _fb_battery(draw, size, color, lw)
    elif "gauge" in n or "speedometer" in n or "pressure" in n:
        _fb_gauge(draw, size, color, lw)
    elif "fire" in n or "flame" in n or "gas" in n or "smoke" in n:
        _fb_flame(draw, size, color, lw)
    elif "wind" in n or "weather" in n or "wave" in n or "sine" in n or "current-ac" in n:
        _fb_wind(draw, size, color, lw)
    elif "molecule" in n or "air" in n or "filter" in n or "motion" in n or "sensor" in n:
        _fb_dots(draw, size, color, lw)
    elif "door" in n or "garage" in n or "window" in n:
        _fb_door(draw, size, color, lw, is_open="open" in n)
    elif "robot" in n or "script" in n or "palette" in n or "text" in n:
        _fb_chip(draw, size, color, lw)
    elif "play-pause" in n:
        _fb_play(draw, size, color)
        _fb_pause(draw, size, color, lw, right_half=True)
    elif "play" in n:
        _fb_play(draw, size, color)
    elif "pause" in n:
        _fb_pause(draw, size, color, lw)
    elif "skip-next" in n:
        _fb_skip_next(draw, size, color, lw)
    elif "skip-previous" in n:
        _fb_skip_prev(draw, size, color, lw)
    elif "volume-plus" in n or "volume-high" in n:
        _fb_volume(draw, size, color, lw, up=True)
    elif "volume-minus" in n or "volume-low" in n or "volume-medium" in n:
        _fb_volume(draw, size, color, lw, up=False)
    elif "shuffle" in n:
        _fb_shuffle(draw, size, color, lw)
    elif "repeat" in n:
        _fb_repeat(draw, size, color, lw)
    else:
        _fb_power(draw, size, color, lw)

    return img


# ── Individual fallback shapes ────────────────────────────────────────────────


def _fb_toggle(draw, s, c, lw, is_on):
    pad = s // 8
    h = s // 2
    y0 = (s - h) // 2
    y1 = y0 + h
    r = h // 2
    draw.rounded_rectangle([pad, y0, s - pad, y1], radius=r, outline=c, width=lw)
    kr = r - lw - 1
    kx = (s - pad - r) if is_on else (pad + r)
    ky = (y0 + y1) // 2
    if kr > 0:
        draw.ellipse([kx - kr, ky - kr, kx + kr, ky + kr], fill=c)


def _fb_bulb(draw, s, c, lw, outline_only):
    pad = s // 6
    cx = s // 2
    r = s // 2 - pad
    draw.arc([cx - r, pad, cx + r, pad + r * 2], start=0, end=360, fill=c, width=lw)
    if not outline_only:
        draw.chord([cx - r, pad, cx + r, pad + r * 2], start=180, end=360, fill=c)
    base = pad + r * 2 + 1
    for i in range(3):
        y = base + i * (lw + 1)
        off = pad + r // 3 + i * 2
        draw.line([(cx - r + off, y), (cx + r - off, y)], fill=c, width=lw)


def _fb_eye(draw, s, c, lw, open_):
    cx, cy = s // 2, s // 2
    rx, ry = s // 2 - s // 6, s // 4
    draw.arc([cx - rx, cy - ry, cx + rx, cy + ry], start=200, end=340, fill=c, width=lw)
    draw.arc([cx - rx, cy - ry, cx + rx, cy + ry], start=20, end=160, fill=c, width=lw)
    if open_:
        pr = max(2, s // 6)
        draw.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], outline=c, width=lw)
    else:
        draw.line(
            [(s // 5, cy + ry // 2), (s - s // 5, cy - ry // 2)],
            fill=c,
            width=lw + 1,
        )


def _fb_lock(draw, s, c, lw, unlocked):
    pad = s // 5
    bx0, by0 = pad, s // 2
    bx1, by1 = s - pad, s - pad // 2
    draw.rounded_rectangle([bx0, by0, bx1, by1], radius=lw * 2, outline=c, width=lw)
    cx = s // 2
    ar = (bx1 - bx0) // 3
    ay1 = by0
    ay0 = by0 - ar
    if unlocked:
        draw.arc([cx, ay0, cx + ar * 2, ay1 + ar], start=200, end=360, fill=c, width=lw)
    else:
        draw.arc([cx - ar, ay0, cx + ar, ay1], start=180, end=360, fill=c, width=lw)


def _fb_fan(draw, s, c, lw):
    cx, cy = s // 2, s // 2
    r = s // 2 - s // 6
    for angle in (0, 120, 240):
        a = math.radians(angle)
        x1 = cx + int(r * 0.3 * math.cos(a))
        y1 = cy + int(r * 0.3 * math.sin(a))
        x2 = cx + int(r * math.cos(a))
        y2 = cy + int(r * math.sin(a))
        draw.arc(
            [x2 - s // 5, y2 - s // 5, x2 + s // 5, y2 + s // 5],
            start=angle + 90,
            end=angle + 270,
            fill=c,
            width=lw,
        )
        draw.line([(x1, y1), (x2, y2)], fill=c, width=lw)
    pr = max(2, s // 8)
    draw.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=c)


def _fb_house(draw, s, c, lw):
    pad = s // 6
    cx = s // 2
    draw.polygon([(cx, pad), (s - pad, s // 2), (pad, s // 2)], outline=c, width=lw)
    draw.rectangle([pad + lw, s // 2, s - pad - lw, s - pad], outline=c, width=lw)
    dw = s // 5
    draw.rectangle(
        [cx - dw // 2, s - pad - s // 4, cx + dw // 2, s - pad - lw],
        outline=c,
        width=lw,
    )


def _fb_thermo(draw, s, c, lw):
    cx = s // 2
    br = s // 5
    tr = max(3, br // 2)
    ty = s // 5
    by0 = s - s // 5 - br
    draw.line([(cx, ty + tr), (cx, by0)], fill=c, width=tr * 2)
    draw.ellipse([cx - br, by0, cx + br, by0 + br * 2], fill=c)
    draw.arc([cx - tr, ty, cx + tr, ty + tr * 2], start=0, end=360, fill=c, width=lw)
    for y in range(ty + tr * 2 + 2, by0 - 2, s // 6):
        draw.line([(cx + tr, y), (cx + s // 6, y)], fill=c, width=lw)


def _fb_speaker(draw, s, c, lw, muted):
    pad = s // 5
    bx = pad + s // 5
    draw.polygon(
        [
            (pad, s // 2 - s // 8),
            (bx, s // 2 - s // 5),
            (bx, s // 2 + s // 5),
            (pad, s // 2 + s // 8),
        ],
        outline=c,
        width=lw,
    )
    if not muted:
        r1, r2 = s // 4, s // 3
        draw.arc(
            [bx, s // 2 - r1, bx + r1 * 2, s // 2 + r1],
            start=300,
            end=60,
            fill=c,
            width=lw,
        )
        draw.arc(
            [bx - lw, s // 2 - r2, bx + r2 * 2, s // 2 + r2],
            start=300,
            end=60,
            fill=c,
            width=lw,
        )
    else:
        draw.line(
            [(bx + s // 8, s // 2 - s // 8), (s - pad, s // 2 + s // 8)],
            fill=c,
            width=lw + 1,
        )


def _fb_folder(draw, s, c, lw):
    pad = s // 6
    tab_w = s // 3
    tab_h = max(lw + 2, s // 8)
    tab_x0 = pad
    tab_y0 = pad
    draw.rounded_rectangle(
        [tab_x0, tab_y0, tab_x0 + tab_w, tab_y0 + tab_h],
        radius=lw,
        outline=c,
        width=lw,
    )
    body_y0 = tab_y0 + tab_h - lw
    draw.rounded_rectangle([pad, body_y0, s - pad, s - pad], radius=lw, outline=c, width=lw)


def _fb_arrow_left(draw, s, c, lw):
    cy = s // 2
    pad = s // 5
    tip_x = pad
    head_h = s // 3
    draw.polygon(
        [
            (tip_x, cy),
            (tip_x + head_h, cy - head_h // 2),
            (tip_x + head_h, cy + head_h // 2),
        ],
        fill=c,
    )
    shaft_y = cy - lw
    shaft_x0 = tip_x + head_h - lw
    shaft_x1 = s - pad
    draw.rectangle([shaft_x0, shaft_y, shaft_x1, shaft_y + lw * 2], fill=c)


def _fb_water_drop(draw, s, c, lw):
    cx = s // 2
    pad = s // 6
    r = s // 3
    by = s - pad - r
    draw.polygon([(cx, pad), (cx - r + lw, by), (cx + r - lw, by)], outline=c, width=lw)
    draw.ellipse([cx - r, by - r, cx + r, by + r], outline=c, width=lw)


def _fb_lightning(draw, s, c, lw):
    pad = s // 6
    cx = s // 2
    draw.polygon(
        [
            (cx + s // 7, pad),
            (cx - s // 8, cx - s // 16),
            (cx + s // 10, cx - s // 16),
            (cx - s // 7, s - pad),
            (cx + s // 8, cx + s // 16),
            (cx - s // 10, cx + s // 16),
        ],
        fill=c,
    )


def _fb_battery(draw, s, c, lw):
    pad = s // 5
    bh = s // 3
    by0 = (s - bh) // 2
    by1 = by0 + bh
    bx0 = pad
    bx1 = s - pad - s // 9
    draw.rectangle([bx0, by0, bx1, by1], outline=c, width=lw)
    fill_w = int((bx1 - bx0 - lw * 2) * 0.7)
    draw.rectangle([bx0 + lw, by0 + lw, bx0 + lw + fill_w, by1 - lw], fill=c)
    nub_h = bh // 3
    draw.rectangle([bx1, (s - nub_h) // 2, s - pad, (s + nub_h) // 2], fill=c)


def _fb_gauge(draw, s, c, lw):
    pad = s // 7
    cx = s // 2
    cy = s // 2 + s // 10
    r = s // 2 - pad
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=220, end=320, fill=c, width=lw + 1)
    a = math.radians(270 + 20)
    nx = cx + int((r - lw * 3) * math.cos(a))
    ny = cy + int((r - lw * 3) * math.sin(a))
    draw.line([(cx, cy), (nx, ny)], fill=c, width=lw)
    draw.ellipse([cx - lw, cy - lw, cx + lw, cy + lw], fill=c)


def _fb_flame(draw, s, c, lw):
    cx = s // 2
    pad = s // 7
    draw.polygon(
        [
            (cx, pad),
            (cx + s // 5, s // 3),
            (cx + s // 4, s // 2),
            (cx + s // 6, s * 2 // 3),
            (cx, s - pad),
            (cx - s // 6, s * 2 // 3),
            (cx - s // 4, s // 2),
            (cx - s // 5, s // 3),
        ],
        outline=c,
        width=lw,
    )


def _fb_wind(draw, s, c, lw):
    pad = s // 5
    for i, y in enumerate([s // 3, s // 2, s * 2 // 3]):
        x0 = pad
        x1 = s - pad - i * (s // 8)
        draw.arc(
            [x0, y - s // 9, x0 + s // 5, y + s // 9],
            start=180,
            end=0,
            fill=c,
            width=lw,
        )
        draw.line([(x0 + s // 10, y), (x1, y)], fill=c, width=lw)


def _fb_dots(draw, s, c, lw):
    r = max(2, s // 9)
    positions = [(s // 3, s // 3), (s * 2 // 3, s // 3), (s // 2, s * 2 // 3)]
    for ax, ay in positions:
        draw.ellipse([ax - r, ay - r, ax + r, ay + r], fill=c)
    for (ax, ay), (bx, by) in [
        (positions[0], positions[1]),
        (positions[0], positions[2]),
        (positions[1], positions[2]),
    ]:
        draw.line([(ax, ay), (bx, by)], fill=c, width=lw)


def _fb_door(draw, s, c, lw, is_open=False):
    pad = s // 5
    dw = s - pad * 2
    dh = s - pad - pad // 2
    draw.rectangle([pad, pad // 2, pad + dw, pad // 2 + dh], outline=c, width=lw)
    hx = pad + dw - s // 8
    hy = pad // 2 + dh // 2
    draw.ellipse([hx - lw, hy - lw, hx + lw, hy + lw], fill=c)
    if is_open:
        draw.line(
            [(pad, pad // 2), (pad - s // 8, pad // 2 + s // 5)],
            fill=c,
            width=lw,
        )


def _fb_chip(draw, s, c, lw):
    pad = s // 5
    draw.rounded_rectangle(
        [pad, pad, s - pad, s - pad], radius=lw * 2, outline=c, width=lw
    )
    t = pad + (s - pad * 2) // 3
    draw.line([(pad, t), (s - pad, t)], fill=c, width=lw)
    draw.line([(pad, s - t), (s - pad, s - t)], fill=c, width=lw)
    cx = pad + (s - pad * 2) // 3
    draw.line([(cx, pad), (cx, s - pad)], fill=c, width=lw)
    draw.line([(s - cx, pad), (s - cx, s - pad)], fill=c, width=lw)


def _fb_play(draw, s, c):
    pad = s // 5
    draw.polygon([(pad, pad), (pad, s - pad), (s - pad, s // 2)], fill=c)


def _fb_pause(draw, s, c, lw, right_half=False):
    pad = s // 5
    bw = max(lw + 1, s // 7)
    x0 = (s // 2 + 2) if right_half else pad
    x1 = x0 + bw
    x2 = x1 + s // 8
    x3 = x2 + bw
    draw.rectangle([x0, pad, x1, s - pad], fill=c)
    draw.rectangle([x2, pad, x3, s - pad], fill=c)


def _fb_skip_next(draw, s, c, lw):
    pad = s // 5
    mid = s // 2
    draw.polygon([(pad, pad), (pad, s - pad), (mid, mid)], fill=c)
    draw.polygon([(mid, pad), (mid, s - pad), (s - pad - lw, mid)], fill=c)
    draw.rectangle([s - pad - lw, pad, s - pad, s - pad], fill=c)


def _fb_skip_prev(draw, s, c, lw):
    pad = s // 5
    mid = s // 2
    draw.rectangle([pad, pad, pad + lw, s - pad], fill=c)
    draw.polygon([(s - mid, pad), (s - mid, s - pad), (pad + lw + 1, mid)], fill=c)
    draw.polygon([(s - pad, pad), (s - pad, s - pad), (s - mid + 1, mid)], fill=c)


def _fb_volume(draw, s, c, lw, up=True):
    pad = s // 5
    bx = pad + s // 5
    draw.polygon(
        [
            (pad, s // 2 - s // 8),
            (bx, s // 2 - s // 5),
            (bx, s // 2 + s // 5),
            (pad, s // 2 + s // 8),
        ],
        outline=c,
        width=lw,
    )
    draw.arc(
        [bx, s // 2 - s // 5, bx + s // 5, s // 2 + s // 5],
        start=300,
        end=60,
        fill=c,
        width=lw,
    )
    ry = s // 2
    rx = bx + s // 4
    if up:
        draw.line([(rx, ry - s // 8), (rx, ry + s // 8)], fill=c, width=lw)
    draw.line([(rx - s // 8, ry), (rx + s // 8, ry)], fill=c, width=lw)


def _fb_shuffle(draw, s, c, lw):
    pad = s // 6
    draw.line([(pad, pad), (s - pad, s - pad)], fill=c, width=lw)
    draw.polygon(
        [
            (s - pad, s - pad),
            (s - pad - s // 6, s - pad),
            (s - pad, s - pad - s // 6),
        ],
        fill=c,
    )
    draw.line([(pad, s - pad), (s - pad, pad)], fill=c, width=lw)
    draw.polygon(
        [(s - pad, pad), (s - pad - s // 6, pad), (s - pad, pad + s // 6)],
        fill=c,
    )


def _fb_repeat(draw, s, c, lw):
    pad = s // 6
    r = (s - pad * 2) // 4
    draw.rounded_rectangle(
        [pad, pad, s - pad, s - pad], radius=r, outline=c, width=lw
    )
    ax = s - pad + lw // 2
    ay = s // 2 + r
    draw.polygon(
        [(ax, ay), (ax - s // 8, ay - s // 10), (ax - s // 8, ay + s // 10)],
        fill=c,
    )
    bx = pad - lw // 2
    by = s // 2 - r
    draw.polygon(
        [(bx, by), (bx + s // 8, by - s // 10), (bx + s // 8, by + s // 10)],
        fill=c,
    )


def _fb_power(draw, s, c, lw):
    m = s // 6
    draw.arc([m, m, s - m - 1, s - m - 1], start=50, end=310, fill=c, width=lw)
    cx = s // 2
    draw.line([(cx, 1), (cx, s // 2 - m // 2)], fill=c, width=lw)
