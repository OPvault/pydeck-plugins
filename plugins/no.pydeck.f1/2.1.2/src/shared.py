"""F1 PDK plugin — shared utilities.

Constants, API helpers, caching, image downloads, and editor-facing
``api_drivers`` / ``api_constructors`` endpoints used by ``api_select``
UI fields.

Data sources:
  Jolpica (api.jolpi.ca)    – calendar, session times, official standings
  OpenF1  (api.openf1.org)  – circuit images, driver photos

Jolpica is the primary calendar source.  OpenF1 locks *all* endpoints
behind an API key while a session is running ("Live F1 session in
progress"), which is precisely when a countdown button matters most, so
it is only used to enrich a meeting that Jolpica already described.

The calendar is static data: once fetched, every countdown is computed
locally.  It is therefore cached in memory *and* on disk, and a failed
fetch backs off instead of retrying on the next poll.
"""

from __future__ import annotations

import io
import json
import ssl
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

# ── Constants ──────────────────────────────────────────────────────────────────

API_BASE = "https://api.openf1.org/v1"
JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
UA = "PyDeck-F1-PDK/2.1"
CACHE_TTL = timedelta(hours=1)
RETRY_TTL = timedelta(minutes=5)
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

# Jolpica reports a country *name*, not a code.
COUNTRY_TO_ALPHA2: Dict[str, str] = {
    "australia": "AU", "austria": "AT", "azerbaijan": "AZ",
    "bahrain": "BH", "belgium": "BE", "brazil": "BR", "canada": "CA",
    "china": "CN", "france": "FR", "germany": "DE", "hungary": "HU",
    "india": "IN", "italy": "IT", "japan": "JP", "korea": "KR",
    "malaysia": "MY", "mexico": "MX", "monaco": "MC", "netherlands": "NL",
    "portugal": "PT", "qatar": "QA", "russia": "RU", "saudi arabia": "SA",
    "singapore": "SG", "south korea": "KR", "spain": "ES",
    "turkey": "TR", "uae": "AE", "uk": "GB", "united arab emirates": "AE",
    "united kingdom": "GB", "united states": "US", "usa": "US",
    "vietnam": "VN",
}

# Jolpica gives a start time per session but no end time; these are the
# nominal broadcast durations, used to decide when a session is LIVE.
SESSION_DURATIONS: Dict[str, timedelta] = {
    "Practice 1":        timedelta(minutes=60),
    "Practice 2":        timedelta(minutes=60),
    "Practice 3":        timedelta(minutes=60),
    "Sprint Qualifying": timedelta(minutes=45),
    "Sprint":            timedelta(minutes=60),
    "Qualifying":        timedelta(minutes=60),
    "Race":              timedelta(minutes=120),
}
DEFAULT_SESSION_DURATION = timedelta(minutes=60)

JOLPICA_SESSION_KEYS = (
    ("FirstPractice",    "Practice 1"),
    ("SecondPractice",   "Practice 2"),
    ("ThirdPractice",    "Practice 3"),
    ("SprintQualifying", "Sprint Qualifying"),
    ("SprintShootout",   "Sprint Qualifying"),
    ("Sprint",           "Sprint"),
    ("Qualifying",       "Qualifying"),
)

# ── Module-level caches ────────────────────────────────────────────────────────

_calendar: Dict[int, list] = {}
_calendar_expires: Dict[int, datetime] = {}
_calendar_available: bool = False

_openf1_meetings: Dict[int, list] = {}
_openf1_expires: Dict[int, datetime] = {}

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


# ── HTTPS ──────────────────────────────────────────────────────────────────────

# api.openf1.org chains through ISRG Root X2 up to ISRG Root X1.  Windows keeps
# an *expired* copy of ISRG Root X2 in its CA store, and because
# ``ssl.load_default_certs()`` promotes every store entry to a trust anchor,
# OpenSSL stops at that expired anchor and gives up with ``certificate verify
# failed: certificate has expired`` — while schannel (and every Linux CA
# bundle) happily follows the chain to the still-valid X1.  OpenF1 is the only
# source of circuit images and driver photos, so on Windows that one expired
# anchor is the difference between a rendered track and a blank key.  It is the
# same failure PyDeck's own marketplace works around in ``marketplace/_http.py``.

_SERVER_AUTH_OID = "1.3.6.1.5.5.7.3.1"

# The verification context that last worked, so the search below is paid for
# once per session rather than on every poll.
_ssl_ctx: Optional[ssl.SSLContext] = None


def _anchor_expiry(der: bytes) -> float:
    """``notAfter`` of one DER certificate as a Unix timestamp (0 if unreadable)."""
    probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    try:
        probe.load_verify_locations(cadata=der)
        info = probe.get_ca_certs()
    except (ssl.SSLError, ValueError):
        return 0.0
    return ssl.cert_time_to_seconds(info[0]["notAfter"]) if info else 0.0


def _windows_store_context() -> Optional[ssl.SSLContext]:
    """The Windows trust store rebuilt without its expired anchors."""
    if sys.platform != "win32":
        return None

    now = time.time()
    pem: List[str] = []
    for store in ("ROOT", "CA"):
        try:
            entries = ssl.enum_certificates(store)
        except (OSError, AttributeError):
            continue
        for der, encoding, purposes in entries:
            if encoding != "x509_asn":
                continue
            if purposes is not True and _SERVER_AUTH_OID not in purposes:
                continue
            if _anchor_expiry(der) <= now:
                continue
            pem.append(ssl.DER_cert_to_PEM_cert(der))

    if not pem:
        return None
    # Passing cadata is also what stops create_default_context() from calling
    # load_default_certs() and putting the expired anchors straight back.
    return ssl.create_default_context(cadata="".join(pem))


def _fallback_contexts() -> List[ssl.SSLContext]:
    """Verification contexts to try when the default trust store fails."""
    out: List[ssl.SSLContext] = []
    try:
        import certifi  # noqa: WPS433 -- optional, absent on many installs
        out.append(ssl.create_default_context(cafile=certifi.where()))
    except Exception:
        pass
    ctx = _windows_store_context()
    if ctx is not None:
        out.append(ctx)
    return out


def _is_cert_error(exc: BaseException) -> bool:
    """True when *exc* is a certificate-verification failure."""
    reason = getattr(exc, "reason", None)
    return isinstance(exc, ssl.SSLCertVerificationError) or isinstance(
        reason, ssl.SSLCertVerificationError,
    )


def _urlopen(req: Request, timeout: float = 10):
    """``urlopen`` that retries a certificate failure against other CA sources.

    Anything but a verification error propagates untouched, so a genuine
    network or HTTP problem still surfaces as itself.
    """
    global _ssl_ctx

    if _ssl_ctx is not None:
        return urlopen(req, timeout=timeout, context=_ssl_ctx)

    try:
        return urlopen(req, timeout=timeout)
    except (URLError, ssl.SSLError) as exc:
        if not _is_cert_error(exc):
            raise
        first = exc

    for ctx in _fallback_contexts():
        try:
            resp = urlopen(req, timeout=timeout, context=ctx)
        except (URLError, ssl.SSLError):
            continue
        _ssl_ctx = ctx
        return resp

    raise first


def fetch_json(url: str) -> Any:
    """GET *url* and decode JSON.  Returns ``None`` when the call fails.

    ``None`` means "could not reach the API"; an empty list or dict means
    "the API answered, and had nothing".  Callers must not conflate them —
    that is what made a failed fetch read as "Off Season".
    """
    req = Request(url, headers={"User-Agent": UA})
    try:
        with _urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def parse_dt(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Calendar ───────────────────────────────────────────────────────────────────


def _combine(date: str, time: str) -> Optional[datetime]:
    if not date:
        return None
    try:
        return parse_dt(f"{date}T{time or '12:00:00Z'}")
    except ValueError:
        return None


def _session(name: str, start: datetime) -> Dict[str, Any]:
    end = start + SESSION_DURATIONS.get(name, DEFAULT_SESSION_DURATION)
    return {
        "session_name": name,
        "date_start": start.isoformat(),
        "date_end": end.isoformat(),
    }


def _meeting_from_race(race: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map one Jolpica/Ergast race entry onto the OpenF1 meeting shape."""
    circuit = race.get("Circuit") or {}
    location = circuit.get("Location") or {}

    sessions: List[Dict[str, Any]] = []
    for key, name in JOLPICA_SESSION_KEYS:
        block = race.get(key)
        if not isinstance(block, dict):
            continue
        start = _combine(block.get("date", ""), block.get("time", ""))
        if start is not None:
            sessions.append(_session(name, start))

    race_start = _combine(race.get("date", ""), race.get("time", ""))
    if race_start is not None:
        sessions.append(_session("Race", race_start))
    if not sessions:
        return None
    sessions.sort(key=lambda s: s["date_start"])

    country = location.get("country", "")
    return {
        "meeting_name": race.get("raceName", ""),
        "circuit_short_name": (
            location.get("locality", "") or circuit.get("circuitName", "")
        ),
        "country_code": COUNTRY_TO_ALPHA2.get(country.lower(), ""),
        "date_start": sessions[0]["date_start"],
        "date_end": sessions[-1]["date_end"],
        "circuit_image": "",
        "sessions": sessions,
    }


def _fetch_calendar(year: int) -> Optional[list]:
    """Fetch *year*'s calendar.  ``None`` on failure, ``[]`` if unpublished."""
    data = fetch_json(f"{JOLPICA_BASE}/{year}/races.json?limit=100")
    if not isinstance(data, dict):
        return None
    try:
        races = data["MRData"]["RaceTable"]["Races"]
    except (KeyError, TypeError):
        return None
    meetings = [_meeting_from_race(r) for r in races]
    return [m for m in meetings if m is not None]


def _disk_cache_path(year: int, storage_dir: Optional[Path]) -> Optional[Path]:
    if storage_dir is None:
        return None
    return Path(storage_dir) / "cache" / f"calendar-{year}.json"


def _read_disk_calendar(year: int, storage_dir: Optional[Path]) -> Optional[list]:
    path = _disk_cache_path(year, storage_dir)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        meetings = data.get("meetings")
        return meetings if isinstance(meetings, list) else None
    except Exception:
        return None


def _write_disk_calendar(
    year: int, meetings: list, storage_dir: Optional[Path]
) -> None:
    path = _disk_cache_path(year, storage_dir)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fetched_at": now_utc().isoformat(), "meetings": meetings}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _calendar_for(year: int, storage_dir: Optional[Path]) -> Optional[list]:
    """Return *year*'s meetings, or ``None`` if the calendar is unavailable.

    Honours the TTL whether the last attempt succeeded or failed, so a
    1 s poll loop can never turn into a 1 s request loop.
    """
    now = now_utc()
    expires = _calendar_expires.get(year)
    if expires is not None and now < expires:
        return _calendar.get(year)

    meetings = _fetch_calendar(year)
    if meetings is not None:
        _calendar[year] = meetings
        _calendar_expires[year] = now + CACHE_TTL
        _write_disk_calendar(year, meetings, storage_dir)
        return meetings

    # Unreachable: back off, then fall back to disk, then to a stale
    # in-memory copy.  The calendar is timestamps, so a stale one still
    # produces a correct countdown.
    _calendar_expires[year] = now + RETRY_TTL
    from_disk = _read_disk_calendar(year, storage_dir)
    if from_disk is not None:
        _calendar[year] = from_disk
    return _calendar.get(year)


def _next_meeting(meetings: Optional[list], now: datetime) -> Optional[Dict[str, Any]]:
    if not meetings:
        return None
    future = [m for m in meetings if parse_dt(m["date_end"]) > now]
    if not future:
        return None
    future.sort(key=lambda m: parse_dt(m["date_start"]))
    return future[0]


def get_or_refresh_meeting(
    storage_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """The next meeting that has not finished, or ``None``.

    ``None`` is ambiguous on its own — pair it with
    :func:`schedule_unavailable` to tell "the season is over" apart from
    "the calendar could not be fetched".
    """
    global _calendar_available
    now = now_utc()

    meetings = _calendar_for(now.year, storage_dir)
    _calendar_available = meetings is not None
    upcoming = _next_meeting(meetings, now)
    if upcoming is not None:
        return upcoming

    # Season finished (or not yet started) — roll onto next year's calendar.
    following = _calendar_for(now.year + 1, storage_dir)
    if following is not None:
        _calendar_available = True
    return _next_meeting(following, now)


def schedule_unavailable() -> bool:
    """True when the last calendar lookup could not reach any source."""
    return not _calendar_available


def get_or_refresh_sessions(meeting: Dict[str, Any]) -> list:
    """Sessions for *meeting*.  Bundled with the calendar — no network."""
    return meeting.get("sessions", [])


def clear_session_cache() -> None:
    """Force the next lookup to re-fetch the calendar (button press)."""
    _calendar_expires.clear()
    _openf1_expires.clear()


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


# ── Circuit images (OpenF1) ────────────────────────────────────────────────────


def _openf1_meetings_for(year: int) -> list:
    """OpenF1 meetings for *year*, cached with the same backoff as above.

    Returns ``[]`` while OpenF1 is locked behind its live-session API key.
    """
    now = now_utc()
    expires = _openf1_expires.get(year)
    if expires is not None and now < expires:
        return _openf1_meetings.get(year, [])

    data = fetch_json(f"{API_BASE}/meetings?year={year}")
    if isinstance(data, list) and data:
        _openf1_meetings[year] = data
        _openf1_expires[year] = now + CACHE_TTL
    else:
        _openf1_expires[year] = now + RETRY_TTL
    return _openf1_meetings.get(year, [])


def _circuit_image_url(meeting: Dict[str, Any]) -> str:
    url = meeting.get("circuit_image", "")
    if url:
        return url

    circuit = (meeting.get("circuit_short_name") or "").lower()
    name = (meeting.get("meeting_name") or "").lower()
    if not circuit and not name:
        return ""

    year = parse_dt(meeting["date_start"]).year
    for m in _openf1_meetings_for(year):
        if (
            (circuit and (m.get("circuit_short_name") or "").lower() == circuit)
            or (name and (m.get("meeting_name") or "").lower() == name)
        ):
            return m.get("circuit_image", "")
    return ""


def download_circuit_image(
    meeting: Dict[str, Any], storage_dir: Path, plugin_name: str
) -> str:
    from PIL import Image, ImageOps, ImageFilter

    circuit_name = meeting.get("circuit_short_name", "unknown")
    safe_name = circuit_name.replace(" ", "_").replace("/", "-")
    tracks_dir = Path(storage_dir) / "tracks"
    dest = tracks_dir / f"{safe_name}.png"
    rel_path = f"tracks/{safe_name}.png"

    # Check the disk cache *before* needing a URL: OpenF1 goes dark during
    # a live session, and an already-rendered track must survive that.
    if dest.exists():
        return rel_path

    circuit_image_url = _circuit_image_url(meeting)
    if not circuit_image_url:
        return ""

    try:
        req = Request(circuit_image_url, headers={"User-Agent": UA})
        with _urlopen(req, timeout=15) as resp:
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
        tracks_dir.mkdir(parents=True, exist_ok=True)
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

    data = fetch_json(f"{JOLPICA_BASE}/{now.year}/driverStandings.json")
    try:
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        _cached_standings = lists[0]["DriverStandings"] if lists else []
        _standings_expires = now + STANDINGS_TTL
    except (KeyError, IndexError, TypeError):
        # Keep the last good standings rather than blanking the button.
        _cached_standings = _cached_standings or []
        _standings_expires = now + RETRY_TTL
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

    data = fetch_json(f"{JOLPICA_BASE}/{now.year}/constructorStandings.json")
    try:
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        _cached_constructor_standings = (
            lists[0]["ConstructorStandings"] if lists else []
        )
        _constructor_standings_expires = now + STANDINGS_TTL
    except (KeyError, IndexError, TypeError):
        _cached_constructor_standings = _cached_constructor_standings or []
        _constructor_standings_expires = now + RETRY_TTL
    return _cached_constructor_standings


def fetch_driver_headshot(
    driver_id: str, storage_dir: Path, plugin_name: str
) -> str:
    drivers_dir = Path(storage_dir) / "drivers"
    dest = drivers_dir / f"{driver_id}.png"
    rel_path = f"drivers/{driver_id}.png"

    if dest.exists():
        return rel_path

    last_name = driver_id.split("_")[-1].upper()
    drivers = fetch_json(f"{API_BASE}/drivers?session_key=latest") or []
    headshot_url = ""
    for d in drivers:
        if last_name in d.get("broadcast_name", "").upper():
            headshot_url = d.get("headshot_url", "")
            break

    if not headshot_url:
        return ""

    try:
        req = Request(headshot_url, headers={"User-Agent": UA})
        with _urlopen(req, timeout=15) as resp:
            raw = resp.read()
        drivers_dir.mkdir(parents=True, exist_ok=True)
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
