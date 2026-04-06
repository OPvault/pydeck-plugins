"""F1 Next Race plugin for PyDeck.

Displays a countdown to the next Formula 1 race weekend on a button,
with the official circuit track layout image fetched from the OpenF1 API.

Pressing the button forces an immediate refresh. The background poller
(poll_next_race) updates every 60 seconds, but only pushes a display_update
when the countdown text actually changes.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
import json
from typing import Any, Dict, Optional

# ── Module-level cache ────────────────────────────────────────────────────────

_cached_meeting: Optional[Dict[str, Any]] = None
_cached_sessions: Optional[list] = None
_cached_year: Optional[int] = None
_last_display_text: Optional[str] = None
_cache_expires: Optional[datetime] = None

# How often to re-fetch the calendar (catches new/cancelled events).
_CACHE_TTL = timedelta(hours=1)

# Maps each checkbox config key → the OpenF1 session_name values it covers.
_CONFIG_SESSION_NAMES: Dict[str, set] = {
    "include_practice_1":        {"Practice 1"},
    "include_practice_2":        {"Practice 2"},
    "include_practice_3":        {"Practice 3"},
    "include_sprint_qualifying": {"Sprint Qualifying"},
    "include_qualifying":        {"Qualifying"},
    "include_race":              {"Race"},
    "include_sprint_race":       {"Sprint"},
}

_cached_standings: Optional[list] = None
_standings_expires: Optional[datetime] = None
_cached_constructor_standings: Optional[list] = None
_constructor_standings_expires: Optional[datetime] = None
_STANDINGS_TTL = timedelta(hours=1)

# Team brand colors keyed by Jolpica constructorId.
_TEAM_COLORS: Dict[str, str] = {
    "red_bull":      "#3671C6",
    "ferrari":       "#E8002D",
    "mercedes":      "#27F4D2",
    "mclaren":       "#FF8000",
    "aston_martin":  "#229971",
    "alpine":        "#FF87BC",
    "haas":          "#B6BABD",
    "rb":            "#6692FF",
    "williams":      "#64C4FF",
    "kick_sauber":   "#52E252",
    "sauber":        "#52E252",
}

# Short codes shown on the button (fallback: first 3 chars of constructorId uppercased).
_TEAM_CODES: Dict[str, str] = {
    "red_bull":      "RBR",
    "ferrari":       "FER",
    "mercedes":      "MER",
    "mclaren":       "MCL",
    "aston_martin":  "AMR",
    "alpine":        "ALP",
    "haas":          "HAA",
    "rb":            "RB",
    "williams":      "WIL",
    "kick_sauber":   "SAU",
    "sauber":        "SAU",
}

_PLUGIN_DIR = Path(__file__).parent
_FALLBACK_IMAGE = "plugins/plugin/f1/img/f1.svg"
_STORAGE_DIR = _PLUGIN_DIR.parents[1] / "storage" / "f1"
_STORAGE_REL = "plugins/storage/f1"
_TRACK_STORAGE_DIR = _STORAGE_DIR / "tracks"
_TRACK_STORAGE_REL = f"{_STORAGE_REL}/tracks"
_DRIVER_STORAGE_DIR = _STORAGE_DIR / "drivers"
_DRIVER_STORAGE_REL = f"{_STORAGE_REL}/drivers"
_API_BASE = "https://api.openf1.org/v1"
_JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"

# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _fetch_json(url: str) -> list:
    req = Request(url, headers={"User-Agent": "PyDeck-F1-Plugin/1.0"})
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []


def _parse_dt(iso_str: str) -> datetime:
    """Parse an ISO 8601 datetime string into a timezone-aware datetime."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _get_or_refresh_standings() -> list:
    """Return cached driver standings, re-fetching when the TTL expires."""
    global _cached_standings, _standings_expires
    now = _now_utc()
    if _cached_standings is not None and _standings_expires is not None and now < _standings_expires:
        return _cached_standings
    try:
        req = Request(
            f"{_JOLPICA_BASE}/{now.year}/driverStandings.json",
            headers={"User-Agent": "PyDeck-F1-Plugin/1.0"},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        _cached_standings = lists[0]["DriverStandings"] if lists else []
    except Exception:
        _cached_standings = _cached_standings or []
    _standings_expires = now + _STANDINGS_TTL
    return _cached_standings


def _fetch_driver_headshot(driver_id: str) -> str:
    """Download and cache the driver's headshot PNG from OpenF1.

    Matches on the last segment of the Jolpica driverId (e.g. 'verstappen')
    against OpenF1's broadcast_name (e.g. 'M VERSTAPPEN').
    """
    _DRIVER_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _DRIVER_STORAGE_DIR / f"{driver_id}.png"
    rel_path = f"{_DRIVER_STORAGE_REL}/{driver_id}.png"

    if dest.exists():
        return rel_path

    last_name = driver_id.split("_")[-1].upper()
    drivers = _fetch_json(f"{_API_BASE}/drivers?session_key=latest")
    headshot_url = ""
    for d in drivers:
        if last_name in d.get("broadcast_name", "").upper():
            headshot_url = d.get("headshot_url", "")
            break

    if not headshot_url:
        return _FALLBACK_IMAGE

    try:
        req = Request(headshot_url, headers={"User-Agent": "PyDeck-F1-Plugin/1.0"})
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
        dest.write_bytes(raw)
        return rel_path
    except Exception:
        return _FALLBACK_IMAGE


def _build_driver_display(driver_id: str) -> Optional[Dict[str, Any]]:
    """Build a display_update dict for the given driver_id."""
    standings = _get_or_refresh_standings()
    entry = next((e for e in standings if e["Driver"]["driverId"] == driver_id), None)
    if entry is None:
        return None
    driver = entry["Driver"]
    code = driver.get("code", driver_id[:3].upper())
    pts = entry.get("points", "0")
    pos = entry.get("position", "?")
    image = _fetch_driver_headshot(driver_id)
    return {
        "image": image,
        "text": "",
        "text_labels": {"bottom": f"#{pos}  {pts}pts"},
        "text_bold": True,
        "text_color": "#ffffff",
        "text_size": 10,
        "scroll_enabled": False,
    }


def _get_or_refresh_constructor_standings() -> list:
    """Return cached constructor standings, re-fetching when the TTL expires."""
    global _cached_constructor_standings, _constructor_standings_expires
    now = _now_utc()
    if (
        _cached_constructor_standings is not None
        and _constructor_standings_expires is not None
        and now < _constructor_standings_expires
    ):
        return _cached_constructor_standings
    try:
        req = Request(
            f"{_JOLPICA_BASE}/{now.year}/constructorStandings.json",
            headers={"User-Agent": "PyDeck-F1-Plugin/1.0"},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        _cached_constructor_standings = lists[0]["ConstructorStandings"] if lists else []
    except Exception:
        _cached_constructor_standings = _cached_constructor_standings or []
    _constructor_standings_expires = now + _STANDINGS_TTL
    return _cached_constructor_standings


def _build_constructor_display(constructor_id: str) -> Optional[Dict[str, Any]]:
    """Build a display_update dict for the given constructor_id."""
    standings = _get_or_refresh_constructor_standings()
    entry = next(
        (e for e in standings if e["Constructor"]["constructorId"] == constructor_id),
        None,
    )
    if entry is None:
        return None
    pts = entry.get("points", "0")
    pos = entry.get("position", "?")
    color = _TEAM_COLORS.get(constructor_id, "#e10600")
    code = _TEAM_CODES.get(constructor_id, constructor_id[:3].upper())
    return {
        "color": color,
        "image": "",
        "text": "",
        "text_labels": {"top": code, "bottom": f"#{pos}  {pts}pts"},
        "text_bold": True,
        "text_color": "#ffffff",
        "text_size": 10,
        "scroll_enabled": False,
    }


def _confirmed_race_names(year: int) -> set:
    """Return a set of lowercased race names from the Jolpica/Ergast API.

    Jolpica reflects the official FIA calendar and excludes cancelled rounds,
    unlike OpenF1 which may lag behind real-world calendar changes.
    """
    try:
        req = Request(
            f"{_JOLPICA_BASE}/{year}/races.json?limit=100",
            headers={"User-Agent": "PyDeck-F1-Plugin/1.0"},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        races = data["MRData"]["RaceTable"]["Races"]
        return {r["raceName"].lower() for r in races}
    except Exception:
        return set()


def _find_next_meeting() -> Optional[Dict[str, Any]]:
    """Find the next upcoming race meeting that is on the official calendar.

    Uses Jolpica as the source of truth for which races are actually scheduled
    (OpenF1 can lag behind FIA calendar changes and include cancelled rounds).
    OpenF1 is used only to obtain the circuit_image URL.
    """
    now = _now_utc()
    for year in (now.year, now.year + 1):
        confirmed = _confirmed_race_names(year)
        meetings = _fetch_json(f"{_API_BASE}/meetings?year={year}")
        if not meetings:
            continue

        future = sorted(
            (
                m for m in meetings
                if _parse_dt(m["date_end"]) > now
                and (
                    not confirmed                          # Jolpica unavailable — show all
                    or m["meeting_name"].lower() in confirmed
                )
            ),
            key=lambda m: _parse_dt(m["date_start"]),
        )

        if future:
            return future[0]

    return None


def _get_or_refresh_sessions(meeting: Dict[str, Any]) -> list:
    """Return sessions for the given meeting, caching them for the TTL duration."""
    global _cached_sessions
    if _cached_sessions is not None:
        return _cached_sessions
    _cached_sessions = _fetch_json(
        f"{_API_BASE}/sessions?meeting_key={meeting['meeting_key']}"
    )
    return _cached_sessions


def _find_target_session(
    meeting: Dict[str, Any], config: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Return the earliest upcoming session the user has checked.

    Builds the allowed set from the checkbox config values, then returns the
    session with the lowest date_start that is still in the future.
    Falls back to the Race session (or any remaining session) if nothing in
    the allowed set is still upcoming (e.g. qualifying already happened).
    """
    cfg = config or {}
    allowed: set = set()
    for key, names in _CONFIG_SESSION_NAMES.items():
        if cfg.get(key, key == "include_race"):  # default: only Race ticked
            allowed |= names

    now = _now_utc()
    sessions = _get_or_refresh_sessions(meeting)

    candidates = [
        s for s in sessions
        if s.get("session_name", "") in allowed
        and _parse_dt(s["date_end"]) > now
    ]

    if not candidates:
        # All selected sessions have passed — fall back to the Race session.
        candidates = [
            s for s in sessions
            if _parse_dt(s["date_end"]) > now
        ]

    if not candidates:
        return None

    candidates.sort(key=lambda s: _parse_dt(s["date_start"]))
    return candidates[0]


def _countdown_text(event: Dict[str, Any]) -> str:
    """Build a human-readable countdown string for the given event (meeting or session)."""
    now = _now_utc()
    date_start = _parse_dt(event["date_start"])
    date_end = _parse_dt(event["date_end"])

    if date_start <= now <= date_end:
        return "LIVE"

    delta = date_start - now
    total_seconds = int(delta.total_seconds())

    if total_seconds <= 0:
        return "LIVE"

    days = delta.days
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    if days >= 1:
        return f"{days}d {hours}h {minutes}m"
    if hours >= 1:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _download_circuit_image(meeting: Dict[str, Any]) -> str:
    """Download the circuit image and save it as a transparent RGBA PNG.

    The F1 CDN images have a dark outer background (~0-20 lum), a lighter
    circuit interior (~80-99 lum), and a bright white track outline (~240-255
    lum).  We scale down first, threshold at >200 (only the outline passes),
    dilate to thicken the lines so they survive pydeck's further downscale,
    then save as RGBA with white track on a transparent background.

    The button's `color` field supplies the background colour — this image
    only provides the track overlay.
    """
    from PIL import Image, ImageOps  # Pillow declared in python_dependencies

    circuit_image_url = meeting.get("circuit_image", "")
    circuit_name = meeting.get("circuit_short_name", "unknown")

    if not circuit_image_url:
        return _FALLBACK_IMAGE

    safe_name = circuit_name.replace(" ", "_").replace("/", "-")
    _TRACK_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _TRACK_STORAGE_DIR / f"{safe_name}.png"
    rel_path = f"{_TRACK_STORAGE_REL}/{safe_name}.png"

    if dest.exists():
        return rel_path

    try:
        req = Request(
            circuit_image_url,
            headers={"User-Agent": "PyDeck-F1-Plugin/1.0"},
        )
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()

        from PIL import ImageFilter  # noqa: PLC0415

        src = Image.open(io.BytesIO(raw)).convert("RGB")

        # Scale to a small fixed size FIRST so the track lines are a
        # manageable width before thresholding and dilation.
        # At 240×180 the ~15px-wide track outline from the 960×720 source
        # becomes ~3.75px — thick enough to work with.
        small = src.resize((240, 180), Image.LANCZOS)

        # Threshold at >200: captures only the bright white track outline
        # (240-255 luminance), not the interior region (~80-99 luminance).
        lum = ImageOps.grayscale(small)
        mask = lum.point(lambda p: 255 if p > 200 else 0)

        # Dilate so lines survive pydeck's further downscale to the button size.
        mask = mask.filter(ImageFilter.MaxFilter(7))

        # Build the full-size track layer, then scale it to 80% and centre it
        # on the canvas so there is visible breathing room around the track.
        W, H = 240, 180
        SCALE = 0.8
        tw, th = int(W * SCALE), int(H * SCALE)

        track_full = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        track_full.paste(Image.new("RGBA", (W, H), (255, 255, 255, 255)), mask=mask)

        track_small = track_full.resize((tw, th), Image.LANCZOS)

        canvas = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        x = (W - tw) // 2
        y = (H - th) // 2
        canvas.paste(track_small, (x, y))

        canvas.save(dest, "PNG")
        return rel_path
    except Exception:
        return _FALLBACK_IMAGE


def _build_display(meeting: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a display_update dict for the given meeting."""
    session = _find_target_session(meeting, config)
    countdown = _countdown_text(session if session is not None else meeting)
    image = _download_circuit_image(meeting)

    return {
        "image": image,
        "text": "",
        "text_labels": {"bottom": countdown},
        "text_bold": True,
        "text_color": "#ffffff",
        "text_size": 10,
        "scroll_enabled": False,
    }


def _get_or_refresh_meeting() -> Optional[Dict[str, Any]]:
    """Return the cached next meeting, re-fetching when the TTL expires.

    The cache is refreshed every _CACHE_TTL (1 hour) so calendar changes
    (new events, cancellations) are picked up without restarting pydeck.
    It is also refreshed immediately when the current meeting has ended.
    """
    global _cached_meeting, _cached_sessions, _cached_year, _cache_expires

    now = _now_utc()

    if _cached_meeting is not None and _cache_expires is not None:
        date_end = _parse_dt(_cached_meeting["date_end"])
        if now < date_end and now < _cache_expires:
            return _cached_meeting

    _cached_meeting = _find_next_meeting()
    _cached_sessions = None  # invalidate so sessions are re-fetched for the new meeting
    _cached_year = now.year
    _cache_expires = now + _CACHE_TTL
    return _cached_meeting


# ── Plugin functions ──────────────────────────────────────────────────────────


def next_race(config: Dict[str, Any]) -> Dict[str, Any]:
    """Press handler — immediately refresh the button with the latest race info."""
    global _cached_meeting, _cached_sessions, _last_display_text

    try:
        _cached_sessions = None  # force session re-fetch on manual press
        meeting = _find_next_meeting()
        if meeting is None:
            _last_display_text = "Off Season"
            return {
                "success": True,
                "display_update": {
                    "image": _FALLBACK_IMAGE,
                    "text": "",
                    "text_labels": {"middle": "Off Season"},
                    "text_bold": True,
                    "text_color": "#ffffff",
                    "text_size": 10,
                    "scroll_enabled": False,
                },
            }

        _cached_meeting = meeting
        display = _build_display(meeting, config)
        _last_display_text = display["text_labels"].get("bottom", "")
        return {"success": True, "display_update": display}

    except Exception as exc:
        return {"success": False, "error": f"F1 plugin error: {exc}"}


def poll_next_race(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poller — push display_update only when the countdown text changes."""
    global _last_display_text

    try:
        meeting = _get_or_refresh_meeting()

        if meeting is None:
            new_text = "Off Season"
            if _last_display_text == new_text:
                return {}
            _last_display_text = new_text
            return {
                "display_update": {
                    "image": _FALLBACK_IMAGE,
                    "text": "",
                    "text_labels": {"middle": "Off Season"},
                    "text_bold": True,
                    "text_color": "#ffffff",
                    "text_size": 10,
                    "scroll_enabled": False,
                }
            }

        display = _build_display(meeting, config)
        new_text = display["text_labels"].get("bottom", "")

        if _last_display_text == new_text:
            return {}

        _last_display_text = new_text
        return {"display_update": display}

    except Exception:
        return {}


# ── Driver Points functions ───────────────────────────────────────────────────


def api_drivers(config: Dict[str, Any]) -> list:  # noqa: ARG001
    """Return the current season's driver standings for the editor dropdown."""
    standings = _get_or_refresh_standings()
    result = []
    for entry in standings:
        driver = entry["Driver"]
        name = f"{driver['givenName']} {driver['familyName']}"
        num = driver.get("permanentNumber", "?")
        result.append({"label": f"#{num} {name}", "value": driver["driverId"]})
    return result


def driver_points(config: Dict[str, Any]) -> Dict[str, Any]:
    """Press handler — show the selected driver's points and headshot."""
    try:
        driver_id = (config or {}).get("driver_id", "")
        if not driver_id:
            return {
                "success": True,
                "display_update": {
                    "text": "",
                    "text_labels": {"middle": "Pick a driver"},
                    "text_bold": True,
                    "text_color": "#ffffff",
                    "text_size": 10,
                    "scroll_enabled": False,
                },
            }
        display = _build_driver_display(driver_id)
        if display is None:
            return {"success": False, "error": f"Driver '{driver_id}' not found in standings"}
        return {"success": True, "display_update": display}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def poll_driver_points(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poller — update button when standings change."""
    try:
        driver_id = (config or {}).get("driver_id", "")
        if not driver_id:
            return {}
        display = _build_driver_display(driver_id)
        if display is None:
            return {}
        return {"display_update": display}
    except Exception:
        return {}


# ── Constructor Points functions ──────────────────────────────────────────────


def api_constructors(config: Dict[str, Any]) -> list:  # noqa: ARG001
    """Return the current season's constructor standings for the editor dropdown."""
    standings = _get_or_refresh_constructor_standings()
    return [
        {
            "label": entry["Constructor"]["name"],
            "value": entry["Constructor"]["constructorId"],
        }
        for entry in standings
    ]


def constructor_points(config: Dict[str, Any]) -> Dict[str, Any]:
    """Press handler — show the selected constructor's points and team color."""
    try:
        constructor_id = (config or {}).get("constructor_id", "")
        if not constructor_id:
            return {
                "success": True,
                "display_update": {
                    "text": "",
                    "text_labels": {"middle": "Pick a team"},
                    "text_bold": True,
                    "text_color": "#ffffff",
                    "text_size": 10,
                    "scroll_enabled": False,
                },
            }
        display = _build_constructor_display(constructor_id)
        if display is None:
            return {"success": False, "error": f"Constructor '{constructor_id}' not found in standings"}
        return {"success": True, "display_update": display}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def poll_constructor_points(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poller — update button when standings change."""
    try:
        constructor_id = (config or {}).get("constructor_id", "")
        if not constructor_id:
            return {}
        display = _build_constructor_display(constructor_id)
        if display is None:
            return {}
        return {"display_update": display}
    except Exception:
        return {}
