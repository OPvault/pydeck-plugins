"""Shared utilities for the PDK Weather plugin.

Provides geocoding, MET.no API access, temperature formatting,
and icon downloading used by function/weather.py and function/forecast.py.
"""

from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MET_API = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
NOMINATIM_API = "https://nominatim.openstreetmap.org/search"
ICON_CDN = (
    "https://raw.githubusercontent.com/metno/weathericons/main/"
    "weather/png/{code}.png"
)
USER_AGENT = "PyDeck WeatherPDK/2.0"
CACHE_TTL = 30 * 60

# ---------------------------------------------------------------------------
# Module-level caches (shared across functions via import)
# ---------------------------------------------------------------------------

_api_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_geo_cache: Dict[str, Tuple[float, float]] = {}


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

def resolve_location(raw: Any) -> Tuple[float, float]:
    """Turn a city name or 'lat,lon' string into (lat, lon).

    Results are cached in-memory to avoid repeated Nominatim calls.
    """
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Location is required")

    m = re.match(
        r"^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$", text,
    )
    if m:
        return float(m.group(1)), float(m.group(2))

    key = text.lower()
    if key in _geo_cache:
        return _geo_cache[key]

    qs = urllib.parse.urlencode({"q": text, "format": "json", "limit": 1})
    req = urllib.request.Request(
        f"{NOMINATIM_API}?{qs}", headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        results = json.loads(resp.read().decode())

    if not results:
        raise ValueError(f"Location not found: {text}")

    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    _geo_cache[key] = (lat, lon)
    return lat, lon


# ---------------------------------------------------------------------------
# MET.no API
# ---------------------------------------------------------------------------

def fetch_timeseries(lat: float, lon: float) -> List[Dict[str, Any]]:
    """Fetch the MET.no compact forecast and return the timeseries list.

    Responses are cached for CACHE_TTL seconds per coordinate pair.
    """
    cache_key = f"{lat:.4f},{lon:.4f}"
    now = time.time()

    cached = _api_cache.get(cache_key)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1].get("properties", {}).get("timeseries", [])

    qs = urllib.parse.urlencode({"lat": f"{lat:.4f}", "lon": f"{lon:.4f}"})
    req = urllib.request.Request(
        f"{MET_API}?{qs}", headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode())

    _api_cache[cache_key] = (now, payload)
    return payload.get("properties", {}).get("timeseries", [])


def current_conditions(
    timeseries: List[Dict[str, Any]],
) -> Tuple[float, float, float, str]:
    """Extract (temp, high_today, low_today, symbol_code) from timeseries."""
    if not timeseries:
        return 0.0, 0.0, 0.0, "unknown"

    first = timeseries[0]["data"]
    temp = float(first["instant"]["details"]["air_temperature"])

    symbol = "unknown"
    for period in ("next_1_hours", "next_6_hours", "next_12_hours"):
        code = first.get(period, {}).get("summary", {}).get("symbol_code")
        if code:
            symbol = code
            break

    end_of_day = datetime.now(timezone.utc).replace(
        hour=23, minute=59, second=59,
    )
    temps = []
    for entry in timeseries:
        try:
            dt = datetime.fromisoformat(
                entry["time"].replace("Z", "+00:00"),
            )
            if dt <= end_of_day:
                temps.append(
                    float(entry["data"]["instant"]["details"]["air_temperature"]),
                )
        except (KeyError, ValueError):
            continue

    high = max(temps) if temps else temp
    low = min(temps) if temps else temp
    return temp, high, low, symbol


def pick_forecasts(
    timeseries: List[Dict[str, Any]],
    interval_hours: int = 1,
    skip_current: bool = False,
    count: int = 3,
) -> List[Dict[str, Any]]:
    """Select *count* forecast entries spaced by *interval_hours*.

    Returns list of dicts with keys: temp_c, symbol, iso_time.
    """
    entries: List[Tuple[datetime, Dict[str, Any]]] = []
    for item in timeseries:
        iso = item.get("time", "")
        try:
            dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        entries.append((dt, item))

    if not entries:
        return []

    origin = entries[0][0]
    start = 1 if skip_current else 0
    cursor = 0
    out: List[Dict[str, Any]] = []

    for step in range(start, start + count):
        target = origin + timedelta(hours=interval_hours * step)

        # MET.no switches from hourly to 6-hour intervals beyond
        # ~48h.  Pick the entry whose time-of-day is closest to the
        # target's so daily forecasts show a consistent hour.
        best = None
        best_score = None
        for i in range(cursor, len(entries)):
            dt = entries[i][0]
            if dt < target - timedelta(hours=interval_hours / 2):
                continue
            if dt > target + timedelta(hours=interval_hours / 2):
                break
            # Prefer matching hour-of-day over raw proximity
            tod_diff = abs(dt.hour * 60 + dt.minute
                          - target.hour * 60 - target.minute)
            if tod_diff > 720:
                tod_diff = 1440 - tod_diff
            abs_diff = abs((dt - target).total_seconds())
            score = (tod_diff, abs_diff)
            if best_score is None or score < best_score:
                best = i
                best_score = score
        selected = best
        if selected is None:
            break

        cursor = selected + 1
        _, item = entries[selected]
        data = item.get("data", {})
        details = data.get("instant", {}).get("details", {})

        symbol = "unknown"
        for period in ("next_1_hours", "next_6_hours", "next_12_hours"):
            code = data.get(period, {}).get("summary", {}).get("symbol_code")
            if code:
                symbol = code
                break

        out.append({
            "temp_c": float(details.get("air_temperature", 0)),
            "symbol": symbol,
            "iso_time": str(item.get("time", "")),
        })

    return out


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt_temp(
    temp_c: float,
    unit: str = "C",
    rounding: str = "nearest",
    show_unit: bool = True,
) -> str:
    """Format a Celsius temperature for display."""
    if unit == "F":
        val = temp_c * 9.0 / 5.0 + 32.0
    elif unit == "K":
        val = temp_c + 273.15
    else:
        val = temp_c

    if rounding == "none":
        num = f"{val:.1f}"
    elif rounding == "down":
        num = str(int(math.floor(val)))
    elif rounding == "up":
        num = str(int(math.ceil(val)))
    else:
        num = str(int(round(val)))

    if not show_unit:
        return f"{num}\u00b0" if unit != "K" else num
    if unit == "K":
        return f"{num} K"
    return f"{num}\u00b0{unit}"


def fmt_time(iso_time: str, show_day: bool = False) -> str:
    """Format an ISO timestamp to local 'HH' or 'Day HH'."""
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        local = dt.astimezone()
        return local.strftime("%a %H") if show_day else local.strftime("%H")
    except (ValueError, AttributeError):
        return ""


def is_wide(unit: str, rounding: str) -> bool:
    """True when the formatted string is long enough to risk clipping."""
    return rounding == "none" or unit == "K"


# ---------------------------------------------------------------------------
# Weather-dependent backgrounds
# ---------------------------------------------------------------------------

_WEATHER_BG: Dict[str, Tuple[str, str]] = {
    "clearsky":         ("#0091fe", "#02cdf9"),
    "fair":             ("#2196f3", "#4fc3f7"),
    "partlycloudy":     ("#5a7d9a", "#8ab4d6"),
    "cloudy":           ("#6b7b8d", "#95a5b4"),
    "fog":              ("#8899a6", "#b0bec5"),
    "lightrain":        ("#4a6a7a", "#6d8fa0"),
    "rain":             ("#3d556a", "#576e80"),
    "heavyrain":        ("#2c3e50", "#445566"),
    "lightrainshowers": ("#4a6a7a", "#6d8fa0"),
    "rainshowers":      ("#3d556a", "#576e80"),
    "heavyrainshowers": ("#2c3e50", "#445566"),
    "sleet":            ("#4e6374", "#6a8395"),
    "sleetshowers":     ("#4e6374", "#6a8395"),
    "lightsleet":       ("#5a7585", "#7a95a5"),
    "snow":             ("#7090a8", "#a8c4d8"),
    "snowshowers":      ("#7090a8", "#a8c4d8"),
    "lightsnow":        ("#80a0b8", "#b8d4e8"),
    "heavysnow":        ("#506878", "#7890a0"),
    "heavysnowshowers": ("#506878", "#7890a0"),
    "thunder":          ("#1a1a2e", "#3a3a5e"),
    "rainandthunder":   ("#1a1a2e", "#2d2d4e"),
    "lightrainandthunder": ("#2a2a3e", "#4a4a6e"),
    "heavyrainandthunder": ("#111122", "#222244"),
    "sleetandthunder":  ("#2a2a3e", "#3a4a5e"),
    "snowandthunder":   ("#2a3a4e", "#4a5a6e"),
}

_DEFAULT_BG = ("#0091fe", "#02cdf9")


def weather_bg(symbol: str) -> Tuple[str, str]:
    """Return (top, bottom) gradient hex colours for a weather symbol."""
    base = str(symbol or "").split("_")[0].lower()
    return _WEATHER_BG.get(base, _DEFAULT_BG)


# ---------------------------------------------------------------------------
# Icon management
# ---------------------------------------------------------------------------

def _sanitize_code(code: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(code or "").lower()) or "unknown"


def download_icon(symbol_code: str, storage_dir: Path) -> str:
    """Ensure a weather icon PNG exists in storage, return relative src path."""
    safe = _sanitize_code(symbol_code)
    dst = storage_dir / f"{safe}.png"

    if dst.exists():
        return f"../../storage/{storage_dir.name}/{safe}.png"

    url = ICON_CDN.format(code=safe)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            if data:
                storage_dir.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                return f"../../storage/{storage_dir.name}/{safe}.png"
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        pass
    return ""
