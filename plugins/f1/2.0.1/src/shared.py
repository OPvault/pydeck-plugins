"""F1 PDK plugin — shared utilities.

Constants, API helpers, caching, image downloads, and editor-facing
``api_drivers`` / ``api_constructors`` endpoints used by ``api_select``
UI fields.

Data sources:
  OpenF1  (api.openf1.org)  – meetings, sessions, circuit images, driver photos
  Jolpica (api.jolpi.ca)    – official standings & calendar (Ergast successor)
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

# ── Constants ──────────────────────────────────────────────────────────────────

API_BASE = "https://api.openf1.org/v1"
JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
UA = "PyDeck-F1-PDK/2.0"
CACHE_TTL = timedelta(hours=1)
STANDINGS_TTL = timedelta(hours=1)

CONFIG_SESSION_NAMES: Dict[str, set] = {
    "include_practice_1":        {"Practice 1"},
    "include_practice_2":        {"Practice 2"},
    "include_practice_3":        {"Practice 3"},
    "include_sprint_qualifying": {"Sprint Qualifying"},
    "include_qualifying":        {"Qualifying"},
    "include_race":              {"Race"},
    "include_sprint_race":       {"Sprint"},
}

TEAM_COLORS: Dict[str, str] = {
    "red_bull":     "#3671C6",
    "ferrari":      "#E8002D",
    "mercedes":     "#27F4D2",
    "mclaren":      "#FF8000",
    "aston_martin": "#229971",
    "alpine":       "#FF87BC",
    "haas":         "#B6BABD",
    "rb":           "#6692FF",
    "williams":     "#64C4FF",
    "kick_sauber":  "#52E252",
    "sauber":       "#52E252",
}

SESSION_SHORT: Dict[str, str] = {
    "Practice 1":        "FP1",
    "Practice 2":        "FP2",
    "Practice 3":        "FP3",
    "Sprint Qualifying": "Sprint Qual",
    "Qualifying":        "Qual",
    "Race":              "Race",
    "Sprint":            "Sprint",
}

TEAM_CODES: Dict[str, str] = {
    "red_bull":     "RBR",
    "ferrari":      "FER",
    "mercedes":     "MER",
    "mclaren":      "MCL",
    "aston_martin": "AMR",
    "alpine":       "ALP",
    "haas":         "HAA",
    "rb":           "RB",
    "williams":     "WIL",
    "kick_sauber":  "SAU",
    "sauber":       "SAU",
}

ALPHA3_TO_ALPHA2: Dict[str, str] = {
    "AUS": "AU", "AUT": "AT", "AZE": "AZ", "BEL": "BE", "BRA": "BR",
    "BRN": "BH", "CAN": "CA", "CHN": "CN", "ESP": "ES", "GBR": "GB",
    "HUN": "HU", "ITA": "IT", "JPN": "JP", "KSA": "SA", "MEX": "MX",
    "MON": "MC", "NED": "NL", "QAT": "QA", "SGP": "SG", "UAE": "AE",
    "USA": "US",
}

# ── Module-level caches ────────────────────────────────────────────────────────

_cached_meeting: Optional[Dict[str, Any]] = None
_cached_sessions: Optional[list] = None
_cache_expires: Optional[datetime] = None

_cached_standings: Optional[list] = None
_standings_expires: Optional[datetime] = None
_cached_constructor_standings: Optional[list] = None
_constructor_standings_expires: Optional[datetime] = None

# ── Helpers ────────────────────────────────────────────────────────────────────


def country_flag(code: str) -> str:
    """Convert an ISO country code (2- or 3-letter) to a flag emoji."""
    if not code:
        return ""
    alpha2 = ALPHA3_TO_ALPHA2.get(code.upper(), code.upper())
    if len(alpha2) != 2:
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in alpha2)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fetch_json(url: str) -> list:
    req = Request(url, headers={"User-Agent": UA})
    try:
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return []


def parse_dt(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Race data ──────────────────────────────────────────────────────────────────


def _confirmed_race_names(year: int) -> set:
    try:
        req = Request(
            f"{JOLPICA_BASE}/{year}/races.json?limit=100",
            headers={"User-Agent": UA},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        races = data["MRData"]["RaceTable"]["Races"]
        return {r["raceName"].lower() for r in races}
    except Exception:
        return set()


def _find_next_meeting() -> Optional[Dict[str, Any]]:
    now = now_utc()
    for year in (now.year, now.year + 1):
        confirmed = _confirmed_race_names(year)
        meetings = fetch_json(f"{API_BASE}/meetings?year={year}")
        if not meetings:
            continue
        future = sorted(
            (
                m for m in meetings
                if parse_dt(m["date_end"]) > now
                and (not confirmed or m["meeting_name"].lower() in confirmed)
            ),
            key=lambda m: parse_dt(m["date_start"]),
        )
        if future:
            return future[0]
    return None


def get_or_refresh_meeting() -> Optional[Dict[str, Any]]:
    global _cached_meeting, _cached_sessions, _cache_expires
    now = now_utc()
    if _cached_meeting is not None and _cache_expires is not None:
        date_end = parse_dt(_cached_meeting["date_end"])
        if now < date_end and now < _cache_expires:
            return _cached_meeting
    _cached_meeting = _find_next_meeting()
    _cached_sessions = None
    _cache_expires = now + CACHE_TTL
    return _cached_meeting


def get_or_refresh_sessions(meeting: Dict[str, Any]) -> list:
    global _cached_sessions
    if _cached_sessions is not None:
        return _cached_sessions
    _cached_sessions = fetch_json(
        f"{API_BASE}/sessions?meeting_key={meeting['meeting_key']}"
    )
    return _cached_sessions


def clear_session_cache() -> None:
    global _cached_sessions
    _cached_sessions = None


def find_target_session(
    meeting: Dict[str, Any], config: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    cfg = config or {}
    allowed: set = set()
    for key, names in CONFIG_SESSION_NAMES.items():
        if cfg.get(key, key == "include_race"):
            allowed |= names

    now = now_utc()
    sessions = get_or_refresh_sessions(meeting)
    candidates = [
        s for s in sessions
        if s.get("session_name", "") in allowed
        and parse_dt(s["date_end"]) > now
    ]
    if not candidates:
        candidates = [
            s for s in sessions
            if parse_dt(s["date_end"]) > now
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: parse_dt(s["date_start"]))
    return candidates[0]


def countdown_text(
    event: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> str:
    now = now_utc()
    date_start = parse_dt(event["date_start"])
    date_end = parse_dt(event["date_end"])

    if date_start <= now <= date_end:
        return "LIVE"

    delta = date_start - now
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "LIVE"

    cfg = config or {}
    sd = cfg.get("show_days", True)
    sh = cfg.get("show_hours", True)
    sm = cfg.get("show_minutes", True)
    ss = cfg.get("show_seconds", False)

    days = delta.days
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60

    parts: List[str] = []
    if sd and days > 0:
        parts.append(f"{days}d")
    if sh and (hours > 0 or days > 0):
        parts.append(f"{hours}h")
    if sm:
        parts.append(f"{minutes}m")
    if ss:
        parts.append(f"{seconds}s")

    return " ".join(parts) if parts else ""


def download_circuit_image(
    meeting: Dict[str, Any], storage_dir: Path, plugin_name: str
) -> str:
    from PIL import Image, ImageOps, ImageFilter

    circuit_image_url = meeting.get("circuit_image", "")
    circuit_name = meeting.get("circuit_short_name", "unknown")
    if not circuit_image_url:
        return ""

    safe_name = circuit_name.replace(" ", "_").replace("/", "-")
    tracks_dir = storage_dir / "tracks"
    tracks_dir.mkdir(parents=True, exist_ok=True)
    dest = tracks_dir / f"{safe_name}.png"
    rel_path = f"../../storage/{plugin_name}/tracks/{safe_name}.png"

    if dest.exists():
        return rel_path

    try:
        req = Request(circuit_image_url, headers={"User-Agent": UA})
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()

        src = Image.open(io.BytesIO(raw)).convert("RGB")
        small = src.resize((240, 180), Image.LANCZOS)
        lum = ImageOps.grayscale(small)
        mask = lum.point(lambda p: 255 if p > 200 else 0)
        mask = mask.filter(ImageFilter.MaxFilter(7))

        W, H = 240, 180
        SCALE = 0.8
        tw, th = int(W * SCALE), int(H * SCALE)

        track_full = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        track_full.paste(
            Image.new("RGBA", (W, H), (255, 255, 255, 255)), mask=mask
        )
        track_small = track_full.resize((tw, th), Image.LANCZOS)

        canvas = Image.new("RGBA", (W, H), (255, 255, 255, 0))
        canvas.paste(track_small, ((W - tw) // 2, (H - th) // 2))
        canvas.save(dest, "PNG")
        return rel_path
    except Exception:
        return ""


# ── Standings data ─────────────────────────────────────────────────────────────


def get_or_refresh_standings() -> list:
    global _cached_standings, _standings_expires
    now = now_utc()
    if (
        _cached_standings is not None
        and _standings_expires is not None
        and now < _standings_expires
    ):
        return _cached_standings
    try:
        req = Request(
            f"{JOLPICA_BASE}/{now.year}/driverStandings.json",
            headers={"User-Agent": UA},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        _cached_standings = lists[0]["DriverStandings"] if lists else []
    except Exception:
        _cached_standings = _cached_standings or []
    _standings_expires = now + STANDINGS_TTL
    return _cached_standings


def get_or_refresh_constructor_standings() -> list:
    global _cached_constructor_standings, _constructor_standings_expires
    now = now_utc()
    if (
        _cached_constructor_standings is not None
        and _constructor_standings_expires is not None
        and now < _constructor_standings_expires
    ):
        return _cached_constructor_standings
    try:
        req = Request(
            f"{JOLPICA_BASE}/{now.year}/constructorStandings.json",
            headers={"User-Agent": UA},
        )
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        _cached_constructor_standings = (
            lists[0]["ConstructorStandings"] if lists else []
        )
    except Exception:
        _cached_constructor_standings = _cached_constructor_standings or []
    _constructor_standings_expires = now + STANDINGS_TTL
    return _cached_constructor_standings


def fetch_driver_headshot(
    driver_id: str, storage_dir: Path, plugin_name: str
) -> str:
    drivers_dir = storage_dir / "drivers"
    drivers_dir.mkdir(parents=True, exist_ok=True)
    dest = drivers_dir / f"{driver_id}.png"
    rel_path = f"../../storage/{plugin_name}/drivers/{driver_id}.png"

    if dest.exists():
        return rel_path

    last_name = driver_id.split("_")[-1].upper()
    drivers = fetch_json(f"{API_BASE}/drivers?session_key=latest")
    headshot_url = ""
    for d in drivers:
        if last_name in d.get("broadcast_name", "").upper():
            headshot_url = d.get("headshot_url", "")
            break

    if not headshot_url:
        return ""

    try:
        req = Request(headshot_url, headers={"User-Agent": UA})
        with urlopen(req, timeout=15) as resp:
            raw = resp.read()
        dest.write_bytes(raw)
        return rel_path
    except Exception:
        return ""


# ── API endpoint functions (for api_select UI fields) ──────────────────────────


def api_drivers(config: Dict[str, Any]) -> list:
    standings = get_or_refresh_standings()
    result = []
    for entry in standings:
        driver = entry["Driver"]
        name = f"{driver['givenName']} {driver['familyName']}"
        num = driver.get("permanentNumber", "?")
        result.append({"label": f"#{num} {name}", "value": driver["driverId"]})
    return result


def api_constructors(config: Dict[str, Any]) -> list:
    standings = get_or_refresh_constructor_standings()
    return [
        {
            "label": entry["Constructor"]["name"],
            "value": entry["Constructor"]["constructorId"],
        }
        for entry in standings
    ]
