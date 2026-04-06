"""Weather plugin for PyDeck using met.no Locationforecast API."""

from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_MET_NO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_MET_ICON_URL = (
    "https://raw.githubusercontent.com/metno/weathericons/main/"
    "weather/png/{symbol}.png"
)
_USER_AGENT = "PyDeck WeatherPlugin-v1.0.0"
_PLUGIN_DIR = Path(__file__).parent
_STORAGE_DIR = _PLUGIN_DIR.parents[1] / "storage" / "met" / "images"
_CACHE_TTL_SECONDS = 30 * 60

_weather_cache: Dict[str, Dict[str, Any]] = {}
_display_signatures: Dict[str, str] = {}
_forecast_signatures: Dict[str, str] = {}
_forecast_show_day_cache: Dict[str, bool] = {}
_forecast_last_config_key: Dict[str, str] = {}
_geocode_cache: Dict[str, Tuple[float, float]] = {}


def _config_key(config: Dict[str, Any]) -> str:
    return ":".join(
        str(config.get(k, ""))
        for k in (
            "location",
            "show_condition",
            "temperature_unit",
            "temperature_rounding",
            "show_temperature_unit",
        )
    )


def _forecast_config_key(config: Dict[str, Any]) -> str:
    show_day = _get_show_day_preference(config)
    return ":".join([
        str(config.get("location", "")),
        str(config.get("forecast_interval", "")),
        str(bool(config.get("exclude_current_forecast", False))),
        str(config.get("show_condition", "")),
        str(show_day),
        str(config.get("temperature_unit", "")),
        str(config.get("temperature_rounding", "")),
        str(config.get("show_temperature_unit", "")),
    ])


def _cache_key(config: Dict[str, Any]) -> str:
    location = str(config.get("location") or "").strip().lower()
    return location or "__default_location__"


def _get_show_day_preference(config: Dict[str, Any]) -> bool:
    """Get show_day preference, using cached value if not explicitly set."""
    location_key = _cache_key(config)
    
    if "show_day" in config:
        show_day = bool(config["show_day"])
        _forecast_show_day_cache[location_key] = show_day
        return show_day
    
    if location_key in _forecast_show_day_cache:
        return _forecast_show_day_cache[location_key]
    
    default_value = False
    _forecast_show_day_cache[location_key] = default_value
    return default_value


def _parse_lat_lon(raw: str) -> Optional[Tuple[float, float]]:
    match = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$", raw)
    if not match:
        return None

    lat = float(match.group(1))
    lon = float(match.group(2))
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return None
    return (lat, lon)


def _resolve_location(raw_location: Any) -> Tuple[float, float, str]:
    location = str(raw_location or "").strip()
    if not location:
        raise ValueError("Location is required.")

    lat_lon = _parse_lat_lon(location)
    if lat_lon:
        lat, lon = lat_lon
        return lat, lon, f"{lat:.4f},{lon:.4f}"

    cached = _geocode_cache.get(location.lower())
    if cached:
        lat, lon = cached
        return lat, lon, location

    query = urllib.parse.urlencode(
        {"q": location, "format": "json", "limit": 1}
    )
    req = urllib.request.Request(
        f"{_NOMINATIM_URL}?{query}",
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))

    if not isinstance(payload, list) or not payload:
        raise ValueError(f"Could not resolve location '{location}'.")

    first = payload[0]
    lat = float(first.get("lat", "nan"))
    lon = float(first.get("lon", "nan"))
    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        raise ValueError(f"Invalid coordinates for location '{location}'.")

    _geocode_cache[location.lower()] = (lat, lon)
    return lat, lon, location


def _fetch_metno(lat: float, lon: float) -> Dict[str, Any]:
    query = urllib.parse.urlencode({"lat": f"{lat:.4f}", "lon": f"{lon:.4f}"})
    req = urllib.request.Request(
        f"{_MET_NO_URL}?{query}",
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _extract_weather(payload: Dict[str, Any]) -> Tuple[float, str]:
    props = payload.get("properties")
    if not isinstance(props, dict):
        raise ValueError("Weather API response missing properties.")

    timeseries = props.get("timeseries")
    if not isinstance(timeseries, list) or not timeseries:
        raise ValueError("Weather API response missing timeseries.")

    first = timeseries[0]
    data = first.get("data") if isinstance(first, dict) else None
    if not isinstance(data, dict):
        raise ValueError("Weather API response missing data block.")

    instant = data.get("instant")
    details = instant.get("details") if isinstance(instant, dict) else None
    if not isinstance(details, dict) or "air_temperature" not in details:
        raise ValueError("Weather API response missing air_temperature.")

    temp_c = float(details["air_temperature"])

    symbol = "unknown"
    next_1h = data.get("next_1_hours")
    next_6h = data.get("next_6_hours")
    next_12h = data.get("next_12_hours")

    for candidate in (next_1h, next_6h, next_12h):
        summary = (
            candidate.get("summary") if isinstance(candidate, dict) else None
        )
        symbol_code = (
            summary.get("symbol_code") if isinstance(summary, dict) else None
        )
        if isinstance(symbol_code, str) and symbol_code.strip():
            symbol = symbol_code.strip()
            break

    return temp_c, symbol


def _symbol_to_label(symbol_code: str) -> str:
    label = (
        symbol_code.replace("_day", "")
        .replace("_night", "")
        .replace("_polartwilight", "")
    )
    label = label.replace("_", " ").strip()
    if not label:
        return "Unknown"
    return " ".join(part.capitalize() for part in label.split())


def _safe_symbol(symbol_code: str) -> str:
    value = re.sub(r"[^a-z0-9_]", "", str(symbol_code or "").lower())
    return value or "unknown"


def _download_icon(symbol_code: str) -> Optional[Path]:
    safe_symbol = _safe_symbol(symbol_code)
    _STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    dst = _STORAGE_DIR / f"{safe_symbol}.png"

    if dst.exists():
        return dst

    url = _MET_ICON_URL.format(symbol=safe_symbol)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT},
        method="GET",
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        content = resp.read()
        if not content:
            return None
        dst.write_bytes(content)

    return dst


def _icon_rel_path(symbol_code: str) -> Optional[str]:
    try:
        icon_path = _download_icon(symbol_code)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return None

    if icon_path is None:
        return None
    return f"plugins/storage/met/images/{icon_path.name}"


def _normalize_rounding_mode(config: Dict[str, Any]) -> str:
    mode = str(config.get("temperature_rounding") or "none").strip().lower()
    if mode in {"up", "down", "nearest", "none"}:
        return mode
    return "none"


def _format_temperature(
    temp_c: float,
    unit: str,
    rounding_mode: str = "none",
    show_unit: bool = True,
    include_degree_icon: bool = False,
) -> str:
    temp_value = (temp_c * 9.0 / 5.0) + 32.0 if str(unit).upper() == "F" else temp_c

    if rounding_mode == "up":
        number_text = str(int(math.ceil(temp_value)))
    elif rounding_mode == "down":
        number_text = str(int(math.floor(temp_value)))
    elif rounding_mode == "nearest":
        number_text = str(int(round(temp_value)))
    else:
        number_text = f"{temp_value:.1f}"

    degree_text = "°" if include_degree_icon else ""
    unit_text = str(unit).upper() if show_unit else ""
    return f"{number_text}{degree_text}{unit_text}"


def _build_text(
    config: Dict[str, Any],
    temp_c: float,
) -> str:
    unit = str(config.get("temperature_unit") or "C").upper()
    show_unit = bool(config.get("show_temperature_unit", True))
    rounding_mode = _normalize_rounding_mode(config)
    # Single-temperature view uses a degree icon for better readability.
    return _format_temperature(
        temp_c,
        unit,
        rounding_mode=rounding_mode,
        show_unit=show_unit,
        include_degree_icon=True,
    )


def _build_result(
    config: Dict[str, Any],
    weather_data: Dict[str, Any],
) -> Dict[str, Any]:
    temp_c = float(weather_data["temp_c"])
    symbol_code = str(weather_data["symbol_code"])
    resolved_location = str(weather_data["location"])
    text = _build_text(config, temp_c)
    show_condition = bool(config.get("show_condition", False))
    image_path = _icon_rel_path(symbol_code) if show_condition else None

    display_update: Dict[str, Any] = {
        "text": text,
        "text_size": 22,
    }

    # Explicitly clear prior icon when condition toggle is disabled.
    if show_condition:
        if image_path:
            display_update["image"] = image_path
    else:
        display_update["image"] = None

    return {
        "success": True,
        "location": resolved_location,
        "temperature_c": temp_c,
        "condition": _symbol_to_label(symbol_code),
        "display_update": display_update,
    }


def _get_weather_data(
    config: Dict[str, Any],
    force: bool = False,
) -> Dict[str, Any]:
    key = _cache_key(config)
    now = time.time()
    cached = _weather_cache.get(key)

    if (
        not force
        and cached
        and now - cached["fetched_at"] < _CACHE_TTL_SECONDS
    ):
        return cached["weather_data"]

    lat, lon, resolved_location = _resolve_location(config.get("location"))
    payload = _fetch_metno(lat, lon)
    temp_c, symbol_code = _extract_weather(payload)
    weather_data = {
        "location": resolved_location,
        "temp_c": temp_c,
        "symbol_code": symbol_code,
    }

    _weather_cache[key] = {
        "fetched_at": now,
        "weather_data": weather_data,
    }
    return weather_data


def show_weather(config: Dict[str, Any]) -> Dict[str, Any]:
    """Manual press: fetch and show current weather for the location."""
    try:
        weather_data = _get_weather_data(config, force=True)
        result = _build_result(config, weather_data)
        key = _config_key(config)
        display = result["display_update"]
        image = str(display.get("image") or "")
        text = str(display.get("text") or "")
        _display_signatures[key] = f"{text}|{image}"
        return result
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except urllib.error.HTTPError as exc:
        return {
            "success": False,
            "error": f"Weather API HTTP {exc.code}: {exc.reason}",
        }
    except urllib.error.URLError as exc:
        return {"success": False, "error": f"Network error: {exc.reason}"}


def poll_weather(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll updates only when text/image output changes."""
    try:
        weather_data = _get_weather_data(config)
        result = _build_result(config, weather_data)
        key = _config_key(config)
        display = result["display_update"]
        image = str(display.get("image") or "")
        text = str(display.get("text") or "")
        signature = f"{text}|{image}"

        if _display_signatures.get(key) == signature:
            return {}

        _display_signatures[key] = signature
        return {"display_update": display}
    except (
        ValueError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        OSError,
    ):
        return {}


def _extract_forecast_entries(
    payload: Dict[str, Any],
    interval_hours: int,
    exclude_current_forecast: bool = False,
    count: int = 3,
) -> list[Dict[str, Any]]:
    """Extract forecast entries at regular intervals from timeseries.

    Uses timestamp-based target selection instead of fixed list indexing,
    because MET timeseries spacing may change over the forecast horizon.
    """
    props = payload.get("properties")
    if not isinstance(props, dict):
        raise ValueError("Weather API response missing properties.")

    timeseries = props.get("timeseries")
    if not isinstance(timeseries, list) or not timeseries:
        raise ValueError("Weather API response missing timeseries.")

    parsed_entries: list[tuple[datetime, Dict[str, Any]]] = []
    for entry in timeseries:
        if not isinstance(entry, dict):
            continue
        iso_time = str(entry.get("time") or "").strip()
        if not iso_time:
            continue
        try:
            entry_dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        parsed_entries.append((entry_dt, entry))

    if not parsed_entries:
        return []

    base_dt = parsed_entries[0][0]
    start_step = 1 if exclude_current_forecast else 0
    search_start_idx = 0
    forecasts = []

    for step_idx in range(start_step, start_step + count):
        target_dt = base_dt + timedelta(hours=interval_hours * step_idx)
        selected_idx = None
        for idx in range(search_start_idx, len(parsed_entries)):
            entry_dt, _ = parsed_entries[idx]
            if entry_dt >= target_dt:
                selected_idx = idx
                break

        if selected_idx is None:
            break

        search_start_idx = selected_idx + 1
        _, entry = parsed_entries[selected_idx]
        data = entry.get("data") if isinstance(entry, dict) else None
        if not isinstance(data, dict):
            continue

        instant = data.get("instant")
        details = instant.get("details") if isinstance(instant, dict) else None
        if not isinstance(details, dict) or "air_temperature" not in details:
            continue

        temp_c = float(details["air_temperature"])
        forecast_time = str(entry.get("time") or "")

        symbol = "unknown"
        for candidate in (
            data.get("next_1_hours"),
            data.get("next_6_hours"),
            data.get("next_12_hours"),
        ):
            summary = (
                candidate.get("summary") if isinstance(candidate, dict) else None
            )
            symbol_code = (
                summary.get("symbol_code") if isinstance(summary, dict) else None
            )
            if isinstance(symbol_code, str) and symbol_code.strip():
                symbol = symbol_code.strip()
                break

        forecasts.append({
            "temp_c": temp_c,
            "symbol_code": symbol,
            "offset_hours": interval_hours * step_idx,
            "time": forecast_time,
        })

    return forecasts


def _format_time(iso_time: str, show_day: bool = False) -> str:
    """Format ISO time string to HH format in local timezone, optionally with day."""
    try:
        dt = datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
        local_dt = dt.astimezone()
        if show_day:
            return local_dt.strftime("%a %H")
        return local_dt.strftime("%H")
    except (ValueError, AttributeError):
        return ""


def _build_forecast_display(
    config: Dict[str, Any],
    forecasts: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build display update dict from forecast data."""
    unit = str(config.get("temperature_unit") or "C").upper()
    show_unit = bool(config.get("show_temperature_unit", True))
    rounding_mode = _normalize_rounding_mode(config)
    show_day = _get_show_day_preference(config)
    
    text_labels = {}
    text_label_sizes = {}
    for forecast, position in zip(forecasts, ["top", "middle", "bottom"]):
        temp_str = _format_temperature(
            forecast["temp_c"],
            unit,
            rounding_mode=rounding_mode,
            show_unit=show_unit,
            include_degree_icon=False,
        )
        time_str = _format_time(forecast["time"], show_day=show_day)

        # Day labels take horizontal space. For longer temperatures (e.g. 13.1C),
        # reduce only that row by 1px to avoid clipping.
        if show_day and len(temp_str) >= 5:
            text_label_sizes[position] = 12
        else:
            text_label_sizes[position] = 13 if show_day else 16
        
        if time_str:
            text_labels[position] = f"{time_str}: {temp_str}"
        else:
            text_labels[position] = temp_str
    
    show_condition = bool(config.get("show_condition", False))
    image_path = None
    if show_condition and forecasts:
        image_path = _icon_rel_path(forecasts[0]["symbol_code"])

    display_update: Dict[str, Any] = {
        "text_labels": text_labels,
        "text_label_sizes": text_label_sizes,
        "text": "",
    }

    if show_condition and image_path:
        display_update["image"] = image_path
    else:
        display_update["image"] = None

    return display_update


def show_forecast(config: Dict[str, Any]) -> Dict[str, Any]:
    """Display 3 weather forecasts at configurable intervals."""
    try:
        lat, lon, resolved_location = _resolve_location(config.get("location"))
        payload = _fetch_metno(lat, lon)
        
        interval_hours = int(config.get("forecast_interval", 1))
        if interval_hours < 1:
            interval_hours = 1

        exclude_current_forecast = bool(
            config.get("exclude_current_forecast", False)
        )
        
        forecasts = _extract_forecast_entries(
            payload,
            interval_hours,
            exclude_current_forecast=exclude_current_forecast,
            count=3,
        )
        
        if not forecasts:
            return {
                "success": False,
                "error": "No forecast data available",
            }

        display_update = _build_forecast_display(config, forecasts)
        
        key = _forecast_config_key(config)
        text_labels = display_update.get("text_labels", {})
        image = str(display_update.get("image") or "")
        signature = f"{text_labels.get('top', '')}|{text_labels.get('middle', '')}|{text_labels.get('bottom', '')}|{image}"
        _forecast_signatures[key] = signature

        return {
            "success": True,
            "location": resolved_location,
            "forecasts": [
                {
                    "time": f["time"],
                    "offset_hours": f["offset_hours"],
                    "temperature_c": f["temp_c"],
                    "condition": _symbol_to_label(f["symbol_code"]),
                }
                for f in forecasts
            ],
            "display_update": display_update,
        }
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except urllib.error.HTTPError as exc:
        return {
            "success": False,
            "error": f"Weather API HTTP {exc.code}: {exc.reason}",
        }
    except urllib.error.URLError as exc:
        return {"success": False, "error": f"Network error: {exc.reason}"}


def poll_forecast(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll updates forecast when config or data changes."""
    try:
        lat, lon, resolved_location = _resolve_location(config.get("location"))
        payload = _fetch_metno(lat, lon)
        
        interval_hours = int(config.get("forecast_interval", 1))
        if interval_hours < 1:
            interval_hours = 1

        exclude_current_forecast = bool(
            config.get("exclude_current_forecast", False)
        )
        
        forecasts = _extract_forecast_entries(
            payload,
            interval_hours,
            exclude_current_forecast=exclude_current_forecast,
            count=3,
        )
        
        if not forecasts:
            return {}

        display_update = _build_forecast_display(config, forecasts)
        
        key = _forecast_config_key(config)
        location_key = _cache_key(config)
        
        last_key = _forecast_last_config_key.get(location_key)
        if last_key != key:
            _forecast_last_config_key[location_key] = key
            _forecast_signatures[key] = ""
        
        text_labels = display_update.get("text_labels", {})
        text_label_sizes = display_update.get("text_label_sizes", {})
        image = str(display_update.get("image") or "")
        signature = f"{text_labels.get('top', '')}|{text_labels.get('middle', '')}|{text_labels.get('bottom', '')}|{text_label_sizes.get('top', '')}|{image}"
        
        if _forecast_signatures.get(key) == signature:
            return {}
        
        _forecast_signatures[key] = signature
        return {"display_update": display_update}
    except (
        ValueError,
        urllib.error.HTTPError,
        urllib.error.URLError,
        OSError,
    ):
        return {}
