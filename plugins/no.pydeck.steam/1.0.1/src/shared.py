"""PDK plugin no.pydeck.steam — shared utilities.

Reads the Steam client's own on-disk library (``libraryfolders.vdf`` and the
``appmanifest_*.acf`` files in every library folder) to list installed
games, pulls each game's poster out of Steam's ``appcache/librarycache``,
and launches games through the ``steam://rungameid/`` URL scheme.

The Steamworks SDK runtime is loaded with ctypes for
``SteamAPI_IsSteamRunning`` — ``libsteam_api.so`` on Linux,
``steam_api64.dll`` on Windows. It is deliberately *not* initialised with
``SteamAPI_Init``: that requires impersonating an app id (the SDK's 480 /
Spacewar test app), which would flip the user's Steam status to "In-Game:
Spacewar" every time the deck renders. The SDK also has no public call that
enumerates a user's library (``ISteamAppList`` is restricted and was dropped
from the SDK), so the manifest files are the source of truth for the game
list.

Everything here is platform-neutral apart from three seams, each of which
branches on ``IS_WINDOWS``: where the Steam client keeps its data directory,
where the SDK runtime lives, and how a ``steam://`` URL is handed to the
client. The library, cache and artwork layout underneath the root is the
same on both platforms, so the parsing and poster code is shared verbatim.
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PLUGIN_ID = "no.pydeck.steam"

IS_WINDOWS = os.name == "nt"

# App ids Steam installs as tooling, never as something to launch.
_TOOL_APPIDS = {228980}  # Steamworks Common Redistributables
_TOOL_NAME_RE = re.compile(
    r"^(Proton( \d|\s|$)|Steam Linux Runtime|Steamworks Common|SteamVR$)",
    re.IGNORECASE,
)

_LIST_TTL = 15.0
_games_cache: List[Dict[str, Any]] = []
_games_cache_ts: float = 0.0
_games_cache_sig: tuple = ()


# ---------------------------------------------------------------------------
# Steam install discovery
# ---------------------------------------------------------------------------

def _registry_roots() -> List[Path]:
    """Steam's install path as the Windows client records it in the registry.

    The client writes ``SteamPath`` under HKCU the moment it starts, and the
    installer writes ``InstallPath`` under HKLM, so between them a relocated
    install is found without guessing at drive letters. ``SteamPath`` comes
    back lowercased with forward slashes (``c:/program files (x86)/steam``),
    which ``Path`` on Windows handles as-is.
    """
    try:
        import winreg  # noqa: PLC0415  -- Windows-only, imported behind IS_WINDOWS
    except ImportError:
        return []
    found: List[Path] = []
    for hive, key, value in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                raw, _kind = winreg.QueryValueEx(handle, value)
        except OSError:
            continue
        if isinstance(raw, str) and raw.strip():
            found.append(Path(raw.strip()))
    return found


def _candidate_roots() -> List[Path]:
    """Every directory that might be a Steam data root, best guess first.

    ``STEAM_ROOT`` always wins so a non-standard install can be pointed at
    by hand; an empty value is dropped rather than resolving to the process
    working directory.
    """
    roots: List[Path] = []
    override = os.environ.get("STEAM_ROOT", "").strip()
    if override:
        roots.append(Path(override))

    if IS_WINDOWS:
        roots.extend(_registry_roots())
        # ProgramFiles(x86) is where the installer puts it on 64-bit Windows;
        # the other two cover a 32-bit host and an install moved to the
        # 64-bit program files tree.
        for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
            base = os.environ.get(var, "").strip()
            if base:
                roots.append(Path(base) / "Steam")
    else:
        home = Path.home()
        roots.extend([
            home / ".local" / "share" / "Steam",
            home / ".steam" / "steam",
            home / ".steam" / "root",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".steam" / "steam",
        ])

    seen: set[str] = set()
    unique: List[Path] = []
    for root in roots:
        # Case-insensitive on Windows, and the registry and the environment
        # disagree about case, so the same install can arrive twice.
        key = str(root).casefold() if IS_WINDOWS else str(root)
        if key in seen or not root.is_dir():
            continue
        seen.add(key)
        unique.append(root)
    return unique


def steam_root() -> Optional[Path]:
    """The Steam client's data directory, or ``None`` when Steam isn't installed."""
    for root in _candidate_roots():
        if (root / "steamapps").is_dir() or (root / "appcache").is_dir():
            try:
                return root.resolve()
            except OSError:
                return root
    return None


# ---------------------------------------------------------------------------
# VDF / ACF parsing (KeyValues text format)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text: str) -> Dict[str, Any]:
    """Parse Valve's KeyValues text format into nested dicts.

    Every leaf is a string; duplicate keys keep the last value, which is how
    the Steam client itself resolves them.
    """
    root: Dict[str, Any] = {}
    stack: List[Dict[str, Any]] = [root]
    pending: Optional[str] = None
    for m in _TOKEN_RE.finditer(text):
        s, brace = m.group(1), m.group(2)
        if brace == "{":
            child: Dict[str, Any] = {}
            stack[-1][pending or ""] = child
            stack.append(child)
            pending = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            pending = None
        elif pending is None:
            pending = s.replace('\\"', '"').replace("\\\\", "\\")
        else:
            stack[-1][pending] = s.replace('\\"', '"').replace("\\\\", "\\")
            pending = None
    return root


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def library_folders() -> List[Path]:
    """Every ``steamapps`` directory Steam knows about, primary library first."""
    root = steam_root()
    if root is None:
        return []
    folders: List[Path] = []
    primary = root / "steamapps"
    if primary.is_dir():
        folders.append(primary)
    vdf = parse_vdf(_read_text(primary / "libraryfolders.vdf"))
    entries = vdf.get("libraryfolders") or vdf.get("LibraryFolders") or {}
    for value in entries.values():
        path_str = value.get("path") if isinstance(value, dict) else value
        if not isinstance(path_str, str) or not path_str:
            continue
        candidate = Path(path_str) / "steamapps"
        if candidate.is_dir():
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            if resolved not in [f.resolve() for f in folders]:
                folders.append(candidate)
    return folders


# ---------------------------------------------------------------------------
# Installed games
# ---------------------------------------------------------------------------

def _is_tool(appid: int, name: str) -> bool:
    return appid in _TOOL_APPIDS or bool(_TOOL_NAME_RE.match(name))


def _manifest_signature(folders: List[Path]) -> tuple:
    sig = []
    for folder in folders:
        try:
            sig.append((str(folder), folder.stat().st_mtime_ns))
        except OSError:
            sig.append((str(folder), 0))
    return tuple(sig)


def installed_games(force: bool = False) -> List[Dict[str, Any]]:
    """Installed, launchable games across every library, sorted by name.

    Each entry: ``appid`` (int), ``name``, ``installdir``, ``last_played``
    (epoch seconds), ``library`` (the steamapps folder it lives in).
    Cached for a few seconds and invalidated when a library folder changes.
    """
    global _games_cache, _games_cache_ts, _games_cache_sig

    folders = library_folders()
    now = time.monotonic()
    sig = _manifest_signature(folders)
    if (
        not force
        and _games_cache
        and sig == _games_cache_sig
        and (now - _games_cache_ts) < _LIST_TTL
    ):
        return _games_cache

    seen: set[int] = set()
    games: List[Dict[str, Any]] = []
    for folder in folders:
        for acf in sorted(folder.glob("appmanifest_*.acf")):
            data = parse_vdf(_read_text(acf)).get("AppState") or {}
            try:
                appid = int(data.get("appid") or acf.stem.split("_", 1)[1])
            except (TypeError, ValueError):
                continue
            name = str(data.get("name") or "").strip() or f"App {appid}"
            if appid in seen or _is_tool(appid, name):
                continue
            # StateFlags 4 == fully installed; anything mid-download is skipped
            # so the deck never offers a game that can't start yet.
            try:
                flags = int(data.get("StateFlags") or 0)
            except (TypeError, ValueError):
                flags = 0
            if flags and not (flags & 4):
                continue
            seen.add(appid)
            try:
                last_played = int(data.get("LastPlayed") or 0)
            except (TypeError, ValueError):
                last_played = 0
            games.append({
                "appid": appid,
                "name": name,
                "installdir": str(data.get("installdir") or ""),
                "last_played": last_played,
                "library": str(folder),
            })

    games.sort(key=lambda g: g["name"].casefold())
    _games_cache = games
    _games_cache_ts = now
    _games_cache_sig = sig
    return games


def game_by_appid(appid: int) -> Optional[Dict[str, Any]]:
    for game in installed_games():
        if game["appid"] == appid:
            return game
    return None


def appid_of(config: Dict[str, Any]) -> int:
    """The app id a button is configured for, or 0 when nothing is picked."""
    raw = str(config.get("appid") or "").strip()
    try:
        return int(raw)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# Posters
# ---------------------------------------------------------------------------

# Preferred first. The client stores a 2:3 portrait ("600x900" / "capsule")
# under per-asset hash folders on current builds, and directly under the app
# id folder (or as ``<appid>_library_600x900.jpg``) on older ones.
_POSTER_NAMES = ("library_600x900.jpg", "library_capsule.jpg")
_FALLBACK_NAMES = ("library_header.jpg", "header.jpg")


def poster_path(appid: int) -> Optional[Path]:
    """Steam's cached poster for *appid*, or ``None`` when it hasn't cached one."""
    root = steam_root()
    if root is None:
        return None
    cache = root / "appcache" / "librarycache"
    app_dir = cache / str(appid)
    for names in (_POSTER_NAMES, _FALLBACK_NAMES):
        for name in names:
            direct = app_dir / name
            if direct.is_file():
                return direct
            legacy = cache / f"{appid}_{name}"
            if legacy.is_file():
                return legacy
        if app_dir.is_dir():
            try:
                subdirs = sorted(p for p in app_dir.iterdir() if p.is_dir())
            except OSError:
                subdirs = []
            for sub in subdirs:
                for name in names:
                    cand = sub / name
                    if cand.is_file():
                        return cand
    return None


_ICON_RE = re.compile(r"^[0-9a-f]{40}\.(jpg|jpeg|png)$", re.IGNORECASE)


def icon_path(appid: int) -> Optional[Path]:
    """Steam's small square game icon (the one shown in the client's sidebar).

    Current builds keep it as a hash-named ``.jpg``/``.png`` directly under
    ``librarycache/<appid>/``; older ones as ``librarycache/<appid>_icon.jpg``.
    """
    root = steam_root()
    if root is None:
        return None
    cache = root / "appcache" / "librarycache"
    app_dir = cache / str(appid)
    if app_dir.is_dir():
        try:
            for entry in sorted(app_dir.iterdir()):
                if entry.is_file() and _ICON_RE.match(entry.name):
                    return entry
        except OSError:
            pass
    legacy = cache / f"{appid}_icon.jpg"
    return legacy if legacy.is_file() else None


def logo_path(appid: int) -> Optional[Path]:
    """Steam's transparent game logo — the wordmark it overlays on the library hero."""
    root = steam_root()
    if root is None:
        return None
    cache = root / "appcache" / "librarycache"
    app_dir = cache / str(appid)
    direct = app_dir / "logo.png"
    if direct.is_file():
        return direct
    legacy = cache / f"{appid}_logo.png"
    if legacy.is_file():
        return legacy
    if app_dir.is_dir():
        try:
            for sub in sorted(p for p in app_dir.iterdir() if p.is_dir()):
                cand = sub / "logo.png"
                if cand.is_file():
                    return cand
        except OSError:
            pass
    return None


def _mirror(src: Optional[Path], stem: str, storage_dir: Path) -> str:
    """Copy *src* into plugin storage as ``<stem><suffix>``; return the relative name.

    The renderer only resolves images under the plugin's storage folder, so
    cache files are mirrored there (re-copied whenever Steam refreshes its
    cache). Returns ``""`` when there is nothing to mirror.
    """
    if src is None:
        return ""
    rel = f"{stem}{src.suffix.lower() or '.jpg'}"
    dst = storage_dir / rel
    try:
        if not dst.is_file() or dst.stat().st_mtime < src.stat().st_mtime:
            storage_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    except OSError:
        return rel if dst.is_file() else ""
    return rel


def ensure_poster(appid: int, storage_dir: Path) -> str:
    return _mirror(poster_path(appid), f"poster_{appid}", storage_dir)


def ensure_icon(appid: int, storage_dir: Path) -> str:
    return _mirror(icon_path(appid), f"icon_{appid}", storage_dir)


def _trim_alpha(src: Path, dst: Path) -> bool:
    """Write *src* to *dst* cropped to its opaque bounding box.

    Steam's logos sit inside a 640x360 canvas with uneven transparent
    margins, so drawing the file as-is lands the wordmark off-centre.
    Falls back to ``False`` (caller copies verbatim) if Pillow is missing
    or the file isn't a decodable image.
    """
    try:
        from PIL import Image  # noqa: PLC0415  -- shipped with the core
    except Exception:
        return False
    try:
        with Image.open(src) as im:
            im = im.convert("RGBA")
            bbox = im.getbbox()
            if bbox is None:
                return False
            cropped = im.crop(bbox)
            dst.parent.mkdir(parents=True, exist_ok=True)
            cropped.save(dst)
        return True
    except Exception:
        return False


def ensure_logo(appid: int, storage_dir: Path) -> str:
    src = logo_path(appid)
    if src is None:
        return ""
    rel = f"logo_{appid}.png"
    dst = storage_dir / rel
    try:
        if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
            return rel
    except OSError:
        pass
    if _trim_alpha(src, dst):
        return rel
    return _mirror(src, f"logo_{appid}", storage_dir)


# ---------------------------------------------------------------------------
# Steamworks SDK (libsteam_api.so / steam_api64.dll via ctypes)
# ---------------------------------------------------------------------------

_steam_api_lib: Any = None
_steam_api_tried = False

# The flat Steamworks API is __cdecl on every platform, so ctypes.CDLL is the
# right loader on Windows too.
if IS_WINDOWS:
    _SDK_LIB_NAMES = ("steam_api64.dll", "steam_api.dll")
    _SDK_REDIST_DIRS = ("win64", "win32")
    # The Windows client ships steamclient64.dll but not the SDK runtime, so
    # in practice only STEAMWORKS_SDK finds one. The root and bin/ are still
    # checked because a self-managed install may have dropped it there.
    _SDK_CLIENT_DIRS = ("", "bin")
else:
    _SDK_LIB_NAMES = ("libsteam_api.so",)
    _SDK_REDIST_DIRS = ("linux64", "linux32")
    _SDK_CLIENT_DIRS = (
        "steamrt64", "ubuntu12_64", "linux64", "sdk64", "steamrt32", "ubuntu12_32",
    )


def _sdk_candidates() -> List[Path]:
    paths: List[Path] = []
    sdk_env = os.environ.get("STEAMWORKS_SDK", "").strip()
    if sdk_env:
        sdk_root = Path(sdk_env)
        for arch in _SDK_REDIST_DIRS:
            for name in _SDK_LIB_NAMES:
                paths.append(sdk_root / "redistributable_bin" / arch / name)
        for name in _SDK_LIB_NAMES:
            paths.append(sdk_root / name)
    for root in _candidate_roots():
        for sub in _SDK_CLIENT_DIRS:
            base = root / sub if sub else root
            for name in _SDK_LIB_NAMES:
                paths.append(base / name)
    # Bare names last: let the platform loader search its own path.
    for name in _SDK_LIB_NAMES:
        paths.append(Path(name))
    return paths


def steam_api() -> Any:
    """The loaded Steamworks runtime, or ``None`` if unavailable."""
    global _steam_api_lib, _steam_api_tried
    if _steam_api_tried:
        return _steam_api_lib
    _steam_api_tried = True
    for cand in _sdk_candidates():
        try:
            if cand.name != str(cand) and not cand.is_file():
                continue
            lib = ctypes.CDLL(str(cand))
            lib.SteamAPI_IsSteamRunning.restype = ctypes.c_bool
            _steam_api_lib = lib
            break
        except (OSError, AttributeError):
            continue
    return _steam_api_lib


def _running_from_registry() -> Optional[bool]:
    """Steam's own "am I up" flag on Windows: the ``ActiveProcess`` pid.

    The client writes its pid there on start and zeroes it on exit — the same
    key ``SteamAPI_IsSteamRunning`` reads. A hard crash can leave the pid
    stale, so this is a fallback for when the SDK runtime is absent, not a
    replacement for it.
    """
    try:
        import winreg  # noqa: PLC0415  -- Windows-only, imported behind IS_WINDOWS

        key = r"Software\Valve\Steam\ActiveProcess"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
            raw, _kind = winreg.QueryValueEx(handle, "pid")
    except (ImportError, OSError):
        return None
    try:
        return int(raw) > 0
    except (TypeError, ValueError):
        return None


def steam_running() -> Optional[bool]:
    """Whether the Steam client is up, or ``None`` when it can't be determined.

    ``SteamAPI_IsSteamRunning`` from the SDK when the runtime is loadable.
    The Windows client doesn't ship that runtime — only ``steamclient64.dll``
    — so there the registry flag the SDK itself consults is read directly.
    """
    lib = steam_api()
    if lib is not None:
        try:
            return bool(lib.SteamAPI_IsSteamRunning())
        except Exception:
            pass
    if IS_WINDOWS:
        return _running_from_registry()
    return None


# ---------------------------------------------------------------------------
# Launching
# ---------------------------------------------------------------------------

def steam_executable() -> Optional[Path]:
    """The Steam client binary, or ``None`` when it can't be located.

    On Windows the registry records the exact path the client was started
    from; ``steam.exe`` sits at the root of the data directory otherwise.
    ``steam`` is rarely on ``PATH`` there, so ``which`` is the last resort
    rather than the first.
    """
    if IS_WINDOWS:
        try:
            import winreg  # noqa: PLC0415  -- Windows-only, imported behind IS_WINDOWS

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as handle:
                raw, _kind = winreg.QueryValueEx(handle, "SteamExe")
            if isinstance(raw, str) and raw.strip():
                exe = Path(raw.strip())
                if exe.is_file():
                    return exe
        except (ImportError, OSError):
            pass
        for root in _candidate_roots():
            exe = root / "steam.exe"
            if exe.is_file():
                return exe
    found = shutil.which("steam.exe" if IS_WINDOWS else "steam")
    return Path(found) if found else None


def _launch_command(url: str) -> Optional[List[str]]:
    """The argv that hands *url* to the Steam client, or ``None`` if there is none."""
    exe = steam_executable()
    if exe is not None:
        return [str(exe), url]
    if IS_WINDOWS:
        # explorer.exe hands a URL to the shell's protocol handler, which is
        # what the steam:// registration points back at.
        explorer = shutil.which("explorer.exe") or shutil.which("explorer")
        return [explorer, url] if explorer else None
    if shutil.which("xdg-open"):
        return ["xdg-open", url]
    if shutil.which("flatpak"):
        return ["flatpak", "run", "com.valvesoftware.Steam", url]
    return None


def _detach_kwargs() -> Dict[str, Any]:
    """Popen options that keep the game alive after PyDeck exits."""
    if IS_WINDOWS:
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        return {"creationflags": flags}
    return {"start_new_session": True}


def launch_game(appid: int) -> Dict[str, Any]:
    """Start *appid* through Steam. Steam is started first if it isn't running."""
    if appid <= 0:
        return {"success": False, "error": "No game selected"}
    cmd = _launch_command(f"steam://rungameid/{appid}")
    if cmd is None:
        return {"success": False, "error": "No steam launcher found"}
    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_detach_kwargs(),
        )
    except OSError as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "appid": appid}


# ---------------------------------------------------------------------------
# api_select endpoints
# ---------------------------------------------------------------------------

def api_games(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """Installed games for the game picker, most recently played first."""
    games = sorted(installed_games(force=True), key=lambda g: -g["last_played"])
    return [{"label": g["name"], "value": str(g["appid"])} for g in games]
