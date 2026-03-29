"""Clock plugin for PyDeck — digital and analog live time display.

Pressing the button forces an immediate time refresh.  The background
poller (poll_clock) updates the button every second automatically.

Digital mode: returns the current time as button text.
Analog mode:  renders a clock face PNG and returns its path.
"""

from __future__ import annotations

import hashlib
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image, ImageDraw, ImageFont

# ── Constants ─────────────────────────────────────────────────────────────────

_PLUGIN_DIR = Path(__file__).parent
_PLUGIN_NAME = _PLUGIN_DIR.name          # "clock" — derived, never hard-coded
_IMG_DIR = _PLUGIN_DIR / "img"
_IMG_PREFIX = "plugins/plugin"           # shared root used by all plugin images
_BUTTON_SIZE = 80

# ── Font loading ──────────────────────────────────────────────────────────────

_FONT_SEARCH_PATHS = [
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "Arial.ttf",
    "Helvetica.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Return a font at *size* pt, trying common paths before falling back."""
    for path in _FONT_SEARCH_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


# ── Colour utilities ──────────────────────────────────────────────────────────


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Parse a #RRGGBB hex string into an (R, G, B) tuple."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (0, 0, 0)


def _contrasting_color(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Return white or black depending on the perceived luminance of *rgb*."""
    luminance = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
    return (255, 255, 255) if luminance < 0.5 else (0, 0, 0)


# ── Image generation ──────────────────────────────────────────────────────────


def _draw_analog(
    dt: datetime,
    show_seconds: bool,
    digital_overlay: bool,
    bg_rgb: tuple[int, int, int],
    fg_rgb: tuple[int, int, int],
    size: int = _BUTTON_SIZE,
) -> Image.Image:
    """Render an analog clock face and return a Pillow Image object."""
    img = Image.new("RGB", (size, size), bg_rgb)
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2
    r = size // 2 - 3

    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=fg_rgb, width=1)

    for i in range(12):
        ang = math.radians(i * 30 - 90)
        tick_len = 5 if i % 3 == 0 else 2
        x1 = cx + int((r - tick_len) * math.cos(ang))
        y1 = cy + int((r - tick_len) * math.sin(ang))
        x2 = cx + int(r * math.cos(ang))
        y2 = cy + int(r * math.sin(ang))
        draw.line([(x1, y1), (x2, y2)], fill=fg_rgb, width=1)

    h_ang = math.radians(
        (dt.hour % 12 + dt.minute / 60 + dt.second / 3600) * 30 - 90
    )
    draw.line(
        [(cx, cy),
         (cx + int(r * 0.48 * math.cos(h_ang)),
          cy + int(r * 0.48 * math.sin(h_ang)))],
        fill=fg_rgb, width=3,
    )

    m_ang = math.radians((dt.minute + dt.second / 60) * 6 - 90)
    draw.line(
        [(cx, cy),
         (cx + int(r * 0.72 * math.cos(m_ang)),
          cy + int(r * 0.72 * math.sin(m_ang)))],
        fill=fg_rgb, width=2,
    )

    if show_seconds:
        s_ang = math.radians(dt.second * 6 - 90)
        draw.line(
            [(cx, cy),
             (cx + int(r * 0.78 * math.cos(s_ang)),
              cy + int(r * 0.78 * math.sin(s_ang)))],
            fill=(220, 70, 70), width=1,
        )

    draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=fg_rgb)

    if digital_overlay:
        fmt = "%H:%M:%S" if show_seconds else "%H:%M"
        time_str = dt.strftime(fmt)
        font_size = 9 if show_seconds else 11
        font = _load_font(font_size)
        bbox = draw.textbbox((0, 0), time_str, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (size - tw) // 2
        ty = cy + int(r * 0.48) - th // 2
        shadow = (0, 0, 0) if fg_rgb != (0, 0, 0) else (255, 255, 255)
        for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            draw.text((tx + dx, ty + dy), time_str, fill=shadow, font=font)
        draw.text((tx, ty), time_str, fill=fg_rgb, font=font)

    return img


def _resolve_bg_color(config: Dict[str, Any]) -> str:
    """Return the effective background colour for the analog face.

    Prefers the user-configured ``bg_color`` UI field; falls back to the
    button's display colour (``_button_color``, injected by the poller) so
    the face still looks reasonable when neither is set.
    """
    color = str(config.get("bg_color") or config.get("_button_color") or "#000000").strip()
    return color if color.startswith("#") else "#000000"


def _analog_cfg_hash(config: Dict[str, Any]) -> str:
    """Return a short hash that captures all analog rendering config values."""
    show_secs = bool(config.get("show_seconds", False))
    overlay = bool(config.get("digital_overlay", False))
    bg_color = _resolve_bg_color(config)
    return hashlib.md5(f"{show_secs}:{overlay}:{bg_color}".encode()).hexdigest()[:10]


_cleanup_done: set[str] = set()


def _cleanup_old_analog_files(cfg_hash: str) -> None:
    """Delete analog face files outside the current 3-slot pool.

    Runs once per session per cfg_hash to remove any files left over from
    earlier naming schemes (e.g. two-digit second suffixes 00-59).
    """
    if cfg_hash in _cleanup_done:
        return
    _cleanup_done.add(cfg_hash)
    keep = {f"_clock_{cfg_hash}_{i}.png" for i in range(2)}
    try:
        for p in _IMG_DIR.glob(f"_clock_{cfg_hash}_*.png"):
            if p.name not in keep:
                try:
                    p.unlink()
                except OSError:
                    pass
    except Exception:
        pass


def _render_analog_to_file(config: Dict[str, Any], dt: datetime) -> Optional[str]:
    """Draw the analog face and atomically replace the output file.

    File naming uses a rotation key derived from the current time so that
    the path changes on every render tick.  This ensures the Stream Deck
    listener (which diffs button configs by value) always detects a change
    and pushes the new frame to the physical device.

    - show_seconds=True  → rotation key is the current second (0-59), giving
                           60 cycling files per config — one updated per second.
    - show_seconds=False → rotation key is the current minute (0-59), giving
                           60 cycling files per config — one updated per minute.

    The write itself is atomic (write-to-temp then os.replace) so the image
    endpoint never reads a partially-written PNG.

    Returns the relative path (from the project root) on success, else None.
    """
    show_secs = bool(config.get("show_seconds", False))
    overlay = bool(config.get("digital_overlay", False))
    bg_color = _resolve_bg_color(config)

    bg_rgb = _hex_to_rgb(bg_color)
    fg_rgb = _contrasting_color(bg_rgb)

    try:
        img = _draw_analog(dt, show_secs, overlay, bg_rgb, fg_rgb)

        cfg_hash = _analog_cfg_hash(config)
        # 2-slot ping-pong: alternates between _0.png and _1.png so the path
        # always differs from the previous render — the minimum needed for the
        # Stream Deck listener (which diffs image paths) to detect the change.
        slot = (dt.second % 2) if show_secs else (dt.minute % 2)
        filename = f"_clock_{cfg_hash}_{slot}.png"
        rel_path = f"{_IMG_PREFIX}/{_PLUGIN_NAME}/img/{filename}"
        abs_path = _IMG_DIR / filename
        tmp_path = _IMG_DIR / f"_clock_{cfg_hash}_{slot}.tmp.png"
        _cleanup_old_analog_files(cfg_hash)

        _IMG_DIR.mkdir(parents=True, exist_ok=True)
        img.save(str(tmp_path), format="PNG")
        os.replace(str(tmp_path), str(abs_path))   # atomic on POSIX
        return rel_path
    except Exception:
        return None


# ── Shared display builder ────────────────────────────────────────────────────


def _build_display_update(config: Dict[str, Any], dt: datetime) -> Dict[str, Any]:
    """Return a display_update dict for the given time and button config."""
    style = str(config.get("clock_style") or "digital")
    show_secs = bool(config.get("show_seconds", False))
    fmt = "%H:%M:%S" if show_secs else "%H:%M"

    if style == "analog":
        path = _render_analog_to_file(config, dt)
        if path:
            return {"image": path}
        return {"text": dt.strftime(fmt)}

    return {"text": dt.strftime(fmt)}


# ── Per-config last-seen state ────────────────────────────────────────────────

# Digital: keyed by _digital_text_key — stores the last emitted time string.
_last_digital_text: dict[str, str] = {}

# Analog: keyed by _analog_cfg_hash — stores the last rendered tick string
# ("%H:%M:%S" or "%H:%M") so we only re-render when the hands actually move.
_last_analog_tick: dict[str, str] = {}

# Style tracking: keyed by _button_config_key — detects style switches.
_last_style: dict[str, str] = {}


def _button_config_key(config: Dict[str, Any]) -> str:
    """Return a stable key for a button that does NOT include clock_style.

    Omitting clock_style keeps the key identical when the user switches
    between digital and analog, so _last_style correctly detects transitions
    and coming_from_analog is set accurately.
    """
    return hashlib.md5(
        f"{config.get('show_seconds', False)}:{config.get('bg_color', '')}".encode()
    ).hexdigest()[:12]


def _digital_text_key(config: Dict[str, Any]) -> str:
    """Return a key scoped only to the fields that affect the digital string."""
    return hashlib.md5(
        f"{config.get('show_seconds', False)}".encode()
    ).hexdigest()[:12]


# ── Plugin functions ──────────────────────────────────────────────────────────


def show_clock(config: Dict[str, Any]) -> Dict[str, Any]:
    """Manual press — immediately refresh the button with the current time."""
    try:
        display = _build_display_update(config, datetime.now())
        return {"success": True, "display_update": display}
    except Exception as e:
        return {"success": False, "error": f"Clock error: {e}"}


def poll_clock(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll — update the button display with the current time.

    Analog mode
    -----------
    Only re-renders and emits when the hands have visibly moved:
    - show_seconds=True  → at most once per second  (tick = HH:MM:SS)
    - show_seconds=False → at most once per minute  (tick = HH:MM)
    The image file is written atomically so the image endpoint never reads
    a partial PNG, eliminating the flicker caused by a race condition.

    Style transitions
    -----------------
    - digital → analog: first analog frame always clears the button text.
    - analog → digital: image is cleared and the digital text cache is evicted
      so the current time string is emitted immediately.
    """
    try:
        dt = datetime.now()
        style = str(config.get("clock_style") or "digital")
        show_secs = bool(config.get("show_seconds", False))
        fmt = "%H:%M:%S" if show_secs else "%H:%M"

        btn_key = _button_config_key(config)
        prev_style = _last_style.get(btn_key)
        _last_style[btn_key] = style

        # ── Analog ────────────────────────────────────────────────────────────
        if style == "analog":
            cfg_hash = _analog_cfg_hash(config)

            # Clear tick cache on style switch so the first analog frame always
            # renders (it also carries text="" to wipe any lingering digital text).
            if prev_style != "analog":
                _last_analog_tick.pop(cfg_hash, None)

            tick = dt.strftime(fmt)
            if _last_analog_tick.get(cfg_hash) == tick:
                return {}   # hands haven't moved visibly since last render
            _last_analog_tick[cfg_hash] = tick

            path = _render_analog_to_file(config, dt)
            update: Dict[str, Any] = {"text": ""}   # clear any lingering digital text
            if path:
                update["image"] = path
            else:
                update["text"] = tick                # fallback: render time as text
            return {"display_update": update}

        # ── Digital ───────────────────────────────────────────────────────────
        txt_key = _digital_text_key(config)
        coming_from_analog = prev_style == "analog"
        if coming_from_analog:
            _last_digital_text.pop(txt_key, None)

        time_str = dt.strftime(fmt)
        if _last_digital_text.get(txt_key) == time_str and not coming_from_analog:
            return {}
        _last_digital_text[txt_key] = time_str
        update = {"text": time_str}
        if coming_from_analog:
            update["image"] = None   # clear the analog face image
        return {"display_update": update}

    except Exception:
        return {}
