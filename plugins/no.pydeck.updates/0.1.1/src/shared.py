"""PDK plugin no.pydeck.updates — package-manager detection and update counting.

Every manager is one :class:`Manager` entry: the binary that marks it as
installed, the read-only command that lists pending updates, a parser that
turns that output into a count, and the interactive command a key press can
run in a terminal to actually apply them.

Checks are slow (most go to the network), so each manager runs on its own
background thread with its own cadence. Handlers only read the cache, so
``on_poll`` stays cheap.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional

CHECK_TIMEOUT_S = 180.0
_PIP_NAME = re.compile(r'"name"\s*:')
_APT_UPGRADED = re.compile(r"(\d+) upgraded")
_env = dict(os.environ, LC_ALL="C", LANG="C")


# ── Output parsers ───────────────────────────────────────────────────────────
# (stdout, returncode) -> count; raise ValueError when the check itself failed.

def _lines(out: str, rc: int) -> int:
    return len([l for l in out.splitlines() if l.strip()])


def _skip_header(out: str, rc: int, header_lines: int = 1) -> int:
    lines = [l for l in out.splitlines() if l.strip()]
    return max(0, len(lines) - header_lines) if lines else 0


def _checkupdates(out: str, rc: int) -> int:
    # 0 = updates listed, 2 = nothing to do, 1 = error (no network / db lock).
    if rc == 2:
        return 0
    if rc != 0:
        raise ValueError("checkupdates failed")
    return _lines(out, rc)


def _pacman_qu(out: str, rc: int) -> int:
    return _lines(out, rc) if rc == 0 else 0     # exit 1 = nothing outdated


def _apt(out: str, rc: int) -> int:
    m = _APT_UPGRADED.search(out)
    if not m:
        raise ValueError("unexpected apt output")
    return int(m.group(1))


def _dnf(out: str, rc: int) -> int:
    # check-update: 100 = updates available, 0 = none, 1 = error.
    if rc == 0:
        return 0
    if rc != 100:
        raise ValueError("dnf check-update failed")
    count = 0
    for line in out.splitlines():
        if not line.strip() or line[0] == " " or line.startswith(("Obsoleting", "Last metadata")):
            continue
        parts = line.split()
        if len(parts) >= 3 and "." in parts[0]:
            count += 1
    return count


def _zypper(out: str, rc: int) -> int:
    return len([l for l in out.splitlines() if l.startswith("v ")])


def _flatpak(out: str, rc: int) -> int:
    if rc != 0:
        raise ValueError("flatpak remote-ls failed")
    return _lines(out, rc)


def _snap(out: str, rc: int) -> int:
    return 0 if "up to date" in out.lower() else _skip_header(out, rc)


def _nix(out: str, rc: int) -> int:
    return len([l for l in out.splitlines() if "->" in l])


def _eopkg(out: str, rc: int) -> int:
    return 0 if "No packages to upgrade" in out else _lines(out, rc)


def _emerge(out: str, rc: int) -> int:
    return len([l for l in out.splitlines() if l.startswith("[ebuild")])


def _apk(out: str, rc: int) -> int:
    return len([l for l in out.splitlines() if "Upgrading" in l])


def _pip(out: str, rc: int) -> int:
    return len(_PIP_NAME.findall(out))


def _cargo(out: str, rc: int) -> int:
    return len([l for l in out.splitlines() if l.strip().endswith("Yes")])


class Manager:
    __slots__ = ("id", "label", "short", "binaries", "check", "parse", "update")

    def __init__(self, id: str, label: str, short: str, binaries: List[str],
                 check: Callable[[str], List[str]], parse: Callable[[str, int], int],
                 update: str) -> None:
        self.id = id
        self.label = label
        self.short = short
        self.binaries = binaries
        self.check = check
        self.parse = parse
        self.update = update

    def binary(self) -> Optional[str]:
        for b in self.binaries:
            if shutil.which(b):
                return b
        return None

    def installed(self) -> bool:
        return self.binary() is not None


MANAGERS: List[Manager] = [
    # System package managers
    Manager("pacman", "Pacman (Arch)", "pac", ["checkupdates", "pacman"],
            lambda b: ["checkupdates"] if b == "checkupdates" else ["pacman", "-Qu"],
            lambda o, rc: _checkupdates(o, rc) if shutil.which("checkupdates") else _pacman_qu(o, rc),
            "sudo pacman -Syu"),
    Manager("aur", "AUR helper (paru / yay)", "aur", ["paru", "yay"],
            lambda b: [b, "-Qua", "--color", "never"], _lines, "{bin} -Sua"),
    Manager("apt", "APT (Debian / Ubuntu)", "apt", ["apt-get"],
            lambda b: ["apt-get", "-s", "-o", "Debug::NoLocking=true", "upgrade"], _apt,
            "sudo apt update && sudo apt upgrade"),
    Manager("dnf", "DNF (Fedora / RHEL)", "dnf", ["dnf5", "dnf"],
            lambda b: [b, "-q", "check-update"], _dnf, "sudo {bin} upgrade"),
    Manager("zypper", "Zypper (openSUSE)", "zyp", ["zypper"],
            lambda b: ["zypper", "-q", "--non-interactive", "list-updates"], _zypper,
            "sudo zypper update"),
    Manager("xbps", "XBPS (Void)", "xbps", ["xbps-install"],
            lambda b: ["xbps-install", "-Mun"], _lines, "sudo xbps-install -Su"),
    Manager("eopkg", "eopkg (Solus)", "eopkg", ["eopkg"],
            lambda b: ["eopkg", "list-upgrades", "-N"], _eopkg, "sudo eopkg upgrade"),
    Manager("emerge", "Portage (Gentoo)", "emg", ["emerge"],
            lambda b: ["emerge", "-puDN", "--color=n", "@world"], _emerge,
            "sudo emerge -avuDN @world"),
    Manager("apk", "apk (Alpine)", "apk", ["apk"],
            lambda b: ["apk", "-s", "upgrade"], _apk, "sudo apk upgrade"),
    Manager("pkg", "pkg (FreeBSD)", "pkg", ["pkg"],
            lambda b: ["pkg", "version", "-vl", "<"], _lines, "sudo pkg upgrade"),
    Manager("nix", "Nix", "nix", ["nix-env"],
            lambda b: ["nix-env", "-u", "--dry-run"], _nix, "nix-env -u"),
    Manager("brew", "Homebrew", "brew", ["brew"],
            lambda b: ["brew", "outdated", "--quiet"], _lines, "brew upgrade"),
    # Sandboxed / universal
    Manager("flatpak", "Flatpak", "flat", ["flatpak"],
            lambda b: ["flatpak", "remote-ls", "--updates", "--columns=application"], _flatpak,
            "flatpak update"),
    Manager("snap", "Snap", "snap", ["snap"],
            lambda b: ["snap", "refresh", "--list"], _snap, "sudo snap refresh"),
    # Language-level
    Manager("pip", "pip (user site)", "pip", ["pip3", "pip"],
            lambda b: [b, "list", "--outdated", "--format=json", "--user"], _pip,
            "{bin} list --outdated --user"),
    Manager("npm", "npm (global)", "npm", ["npm"],
            lambda b: ["npm", "outdated", "-g"], _skip_header, "npm update -g"),
    Manager("cargo", "cargo install-update", "cargo", ["cargo-install-update"],
            lambda b: ["cargo", "install-update", "--list"], _cargo, "cargo install-update -a"),
]
BY_ID: Dict[str, Manager] = {m.id: m for m in MANAGERS}


# ── Background checks and cache ──────────────────────────────────────────────

class _Entry:
    __slots__ = ("count", "error", "at", "running", "started", "lock")

    def __init__(self) -> None:
        self.count: Optional[int] = None
        self.error: Optional[str] = None
        self.at = 0.0          # monotonic time of the last finished check
        self.running = False
        self.started = False
        self.lock = threading.Lock()


_cache: Dict[str, _Entry] = {m.id: _Entry() for m in MANAGERS}


def _check(m: Manager) -> None:
    entry = _cache[m.id]
    binary = m.binary()
    if binary is None:
        entry.count, entry.error = None, "not installed"
        entry.at = time.monotonic()
        return
    try:
        proc = subprocess.run(
            m.check(binary), capture_output=True, text=True,
            timeout=CHECK_TIMEOUT_S, env=_env, stdin=subprocess.DEVNULL,
        )
        entry.count = m.parse(proc.stdout or "", proc.returncode)
        entry.error = None
    except subprocess.TimeoutExpired:
        entry.error = "timed out"
    except (ValueError, OSError) as exc:
        entry.error = str(exc) or "check failed"
    finally:
        entry.at = time.monotonic()


def _worker(m: Manager, interval_s: float) -> None:
    entry = _cache[m.id]
    while True:
        with entry.lock:
            entry.running = True
        try:
            _check(m)
        finally:
            entry.running = False
        time.sleep(max(60.0, interval_s))


def ensure_running(ids: List[str], interval_minutes: float) -> None:
    """Start the check thread for every requested manager (once per process)."""
    for mid in ids:
        m = BY_ID.get(mid)
        if m is None:
            continue
        entry = _cache[mid]
        with entry.lock:
            if entry.started:
                continue
            entry.started = True
        threading.Thread(target=_worker, args=(m, interval_minutes * 60.0),
                         name=f"pydeck-updates-{mid}", daemon=True).start()


def refresh_now(ids: List[str]) -> None:
    """Re-run the checks for these managers off-thread, right now."""
    for mid in ids:
        m = BY_ID.get(mid)
        if m is None:
            continue
        entry = _cache[mid]
        with entry.lock:
            if entry.running:
                continue
            entry.running = True

        def run(m: Manager = m, entry: _Entry = entry) -> None:
            try:
                _check(m)
            finally:
                entry.running = False

        threading.Thread(target=run, daemon=True).start()


def truthy(value: Any) -> bool:
    return value is True or str(value).lower() in ("true", "on", "1", "yes")


def selected_ids(cfg: Dict[str, Any]) -> List[str]:
    """Managers this key counts: every one that is installed."""
    return [m.id for m in MANAGERS if m.installed()]


def summary(ids: List[str]) -> Dict[str, Any]:
    """Aggregate the cache for one key's managers."""
    total = 0
    known = False
    parts: List[str] = []
    errors: List[str] = []
    checking = False
    for mid in ids:
        e, m = _cache[mid], BY_ID[mid]
        if e.count is not None:
            known = True
            total += e.count
            if e.count:
                parts.append(f"{e.count} {m.short}")
        if e.error and e.error != "not installed":
            errors.append(f"{m.short}: {e.error}")
        if e.running:
            checking = True
    return {"total": total, "known": known, "parts": parts,
            "errors": errors, "checking": checking}


# ── Terminal launch ──────────────────────────────────────────────────────────

_TERMINALS = [
    ("alacritty", ["-e"]),
    ("x-terminal-emulator", ["-e"]),
    ("kitty", ["-e"]), ("wezterm", ["start", "--"]),
    ("foot", ["-e"]), ("ghostty", ["-e"]), ("konsole", ["-e"]),
    ("gnome-terminal", ["--"]), ("ptyxis", ["--"]), ("xfce4-terminal", ["-x"]),
    ("tilix", ["-e"]), ("terminator", ["-e"]), ("urxvt", ["-e"]), ("xterm", ["-e"]),
]


def find_terminal(preferred: str) -> Optional[List[str]]:
    if preferred.strip():
        parts = shlex.split(preferred)
        if parts and shutil.which(parts[0]):
            return parts if len(parts) > 1 else [parts[0], "-e"]
    env_term = os.environ.get("TERMINAL", "").strip()
    if env_term and shutil.which(env_term):
        return [env_term, "-e"]
    for name, flag in _TERMINALS:
        if shutil.which(name):
            return [name, *flag]
    return None


def update_command(ids: List[str]) -> str:
    return "; ".join(BY_ID[mid].update.format(bin=BY_ID[mid].binary() or BY_ID[mid].binaries[0])
                     for mid in ids)


def run_updates(ids: List[str], preferred_terminal: str) -> Optional[str]:
    """Open a terminal running every selected manager's update command."""
    if not ids:
        return "nothing to update"
    term = find_terminal(preferred_terminal)
    if term is None:
        return "no terminal found"
    script = update_command(ids) + '; echo; printf "Done. Press Enter to close."; read _'
    try:
        subprocess.Popen(term + ["sh", "-c", script], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as exc:
        return str(exc)
    return None
