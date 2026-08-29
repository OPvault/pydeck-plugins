"""Shared utilities for the PDK Cava plugin.

Two halves.  The lower one keeps a ``cava`` process alive in the background
and hands out the newest spectrum frame it produced.  The upper one turns a
frame into a button face: one absolutely positioned box per bar, sized and
coloured by the handler, because ``shared.css`` is interpolated with handler
state before it is parsed -- the Python side computes the numbers and the
stylesheet only spends them.

cava is run in *raw* output mode, printing one line per frame with a
``;``-separated 0-100 value per bar.  A reader thread keeps the most recent
frames.

Frame rate.  PyDeck runs ``on_poll`` at most once a second on the deck
listener, which is useless for a visualiser.  Animated faces, though, are
re-rendered on a fast tick (~15 fps on the deck, ~5 fps in the browser), and
the renderer interpolates ``{placeholders}`` by calling ``str()`` on each
state value at render time.  So the handler stores :class:`LiveKey` objects in
state: ``str()`` on one reads the newest cava frame and returns that key's
geometry or colour for *this* render.  ``on_poll`` only refreshes the
configuration; a no-op ``@keyframes`` in ``shared.css`` is what puts the face
on the fast tick.  When nothing has rendered a face for a while the cava
process is stopped, so an unused profile costs nothing.
"""

from __future__ import annotations

import atexit
import colorsys
import ctypes
import os
import signal
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

MAX_BARS = 32
IDLE_STOP_S = 20.0          # stop cava after this long without a frame request
FRAME_STALE_S = 3.0         # a frame older than this counts as silence


def cava_path() -> Optional[str]:
    return shutil.which("cava")


# ── cava process ─────────────────────────────────────────────────────────────

class _Feed:
    """One running cava process and the frames it has produced."""

    def __init__(self, bars: int, method: str, sensitivity: int, framerate: int) -> None:
        self.bars = bars
        self.method = method
        self.sensitivity = sensitivity
        self.framerate = framerate
        self.key = (bars, method, sensitivity, framerate)

        self._lock = threading.Lock()
        self._pending: List[List[int]] = []
        self._latest: List[int] = [0] * bars
        self._latest_at = 0.0
        self._last_request = time.monotonic()
        self._proc: Optional[subprocess.Popen] = None
        self._config_path: Optional[str] = None
        self._error: Optional[str] = None
        self._stopped = False

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        exe = cava_path()
        if exe is None:
            self._error = "cava not found"
            return
        # One deterministic file per setting, overwritten on every start, so a
        # crash or restart never leaves a trail of configs behind.
        path = os.path.join(
            tempfile.gettempdir(),
            f"pydeck-cava-{os.getuid()}-{self.bars}-{self.method}-{self.sensitivity}-{self.framerate}.conf",
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._config_text())
        self._config_path = path
        try:
            self._proc = subprocess.Popen(
                [exe, "-p", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                bufsize=0,
                preexec_fn=_die_with_parent,
            )
        except OSError as exc:
            self._error = f"cava failed: {exc}"
            self._cleanup_config()
            return
        threading.Thread(target=self._reader, name="pydeck-cava", daemon=True).start()
        threading.Thread(target=self._watchdog, name="pydeck-cava-idle", daemon=True).start()

    def _config_text(self) -> str:
        lines = [
            "[general]",
            f"bars = {self.bars}",
            f"framerate = {self.framerate}",
            f"sensitivity = {self.sensitivity}",
            "autosens = 1",
            "[output]",
            "method = raw",
            "raw_target = /dev/stdout",
            "data_format = ascii",
            "ascii_max_range = 100",
            "bar_delimiter = 59",
            "frame_delimiter = 10",
        ]
        if self.method != "auto":
            lines += ["[input]", f"method = {self.method}"]
        return "\n".join(lines) + "\n"

    def _cleanup_config(self) -> None:
        if self._config_path:
            try:
                os.unlink(self._config_path)
            except OSError:
                pass
            self._config_path = None

    def stop(self) -> None:
        self._stopped = True
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except OSError:
                pass
        self._cleanup_config()

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and not self._stopped

    # -- threads --------------------------------------------------------------

    def _reader(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            # Unbuffered binary readline: a buffered text iterator would sit on
            # a whole 8 KB chunk -- several seconds of frames -- before
            # yielding the first line.
            for raw in iter(proc.stdout.readline, b""):
                parts = raw.decode("ascii", "replace").strip().strip(";").split(";")
                if not parts or parts == [""]:
                    continue
                try:
                    values = [max(0, min(100, int(p))) for p in parts]
                except ValueError:
                    continue
                if len(values) != self.bars:
                    continue
                # cava has read its config by the time it prints a frame.
                self._cleanup_config()
                with self._lock:
                    self._pending.append(values)
                    if len(self._pending) > 64:
                        del self._pending[:-64]
                    self._latest = values
                    self._latest_at = time.monotonic()
        except (OSError, ValueError):
            pass
        finally:
            self._cleanup_config()
            if proc.poll() is None:
                # stdout closed while the process lives: treat as stopped.
                pass
            elif proc.returncode not in (0, None, -15, -9) and not self._stopped:
                self._error = f"cava exited ({proc.returncode})"

    def _watchdog(self) -> None:
        while self.alive:
            time.sleep(1.0)
            if time.monotonic() - self._last_request > IDLE_STOP_S:
                self.stop()
                break

    # -- frames ---------------------------------------------------------------

    def frame(self, mode: str) -> Tuple[List[int], Optional[str]]:
        """The bars for this poll, plus an error string when cava is not running."""
        self._last_request = time.monotonic()
        with self._lock:
            pending, self._pending = self._pending, []
            latest = list(self._latest)
            latest_at = self._latest_at
        if self._error:
            return [0] * self.bars, self._error
        if time.monotonic() - latest_at > FRAME_STALE_S:
            return [0] * self.bars, None
        if mode == "peak" and pending:
            return [max(col) for col in zip(*pending)], None
        if mode == "average" and pending:
            return [round(sum(col) / len(col)) for col in zip(*pending)], None
        return latest, None


def _die_with_parent() -> None:
    """Ask the kernel to SIGTERM cava if the PyDeck process goes away.

    The idle watchdog only runs while this interpreter does; without this a
    restart of PyDeck would leave an orphaned cava capturing audio for nothing.
    Linux only -- elsewhere it silently does nothing.
    """
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass


_FEED_LOCK = threading.Lock()
_FEEDS: Dict[Tuple[int, str, int, int], _Feed] = {}


def get_frame(
    bars: int, method: str, sensitivity: int, framerate: int, mode: str,
) -> Tuple[List[int], Optional[str]]:
    """Return the current spectrum for this configuration, starting cava if needed."""
    key = (bars, method, sensitivity, framerate)
    with _FEED_LOCK:
        feed = _FEEDS.get(key)
        if feed is None or not feed.alive:
            if feed is not None and feed._error and not feed._stopped:
                # Failed start: report, but retry only every few seconds so a
                # missing binary does not spawn a process per poll.
                if time.monotonic() - feed._last_request < 5.0:
                    return feed.frame(mode)
            feed = _Feed(bars, method, sensitivity, framerate)
            feed.start()
            _FEEDS[key] = feed
        # Drop feeds for configurations no button uses any more.
        for k in list(_FEEDS):
            if k != key and not _FEEDS[k].alive:
                del _FEEDS[k]
    return feed.frame(mode)


def _stop_all() -> None:
    with _FEED_LOCK:
        feeds = list(_FEEDS.values())
    for feed in feeds:
        feed.stop()


atexit.register(_stop_all)


# ── Colour ───────────────────────────────────────────────────────────────────

def _hex_to_rgb(value: str) -> Tuple[int, int, int]:
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except (ValueError, IndexError):
        return 255, 255, 255


def _rgb_to_hex(rgb: Tuple[float, float, float]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(round(c)))) for c in rgb))


def lerp_hex(a: str, b: str, t: float) -> str:
    ra, rb = _hex_to_rgb(a), _hex_to_rgb(b)
    t = max(0.0, min(1.0, t))
    return _rgb_to_hex(tuple(ra[i] + (rb[i] - ra[i]) * t for i in range(3)))


def rainbow_hex(t: float, sat: float = 0.85, light: float = 0.55) -> str:
    r, g, b = colorsys.hls_to_rgb(t % 1.0, light, sat)
    return _rgb_to_hex((r * 255, g * 255, b * 255))


def bar_color(mode: str, cfg: Dict[str, Any], index: int, count: int, level: float) -> str:
    low = str(cfg.get("bar_color") or "#4f9cf9")
    high = str(cfg.get("bar_color_high") or "#ff4f7a")
    if mode == "gradient":
        return lerp_hex(low, high, level)
    if mode == "spread":
        return lerp_hex(low, high, index / max(1, count - 1))
    if mode == "rainbow":
        return rainbow_hex(index / max(1, count))
    return low


# ── Geometry ─────────────────────────────────────────────────────────────────

def pct(value: float) -> str:
    return f"{value:.2f}%"


GAPS = {"none": 0.0, "thin": 1.5, "normal": 3.0, "wide": 5.0}


def cfg_int(cfg: Dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(float(cfg.get(key, default)))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))


def face_state(cfg: Dict[str, Any], values: List[int], error: Optional[str]) -> Dict[str, Any]:
    """Build every render key the template and stylesheet read."""
    n = len(values)
    style = str(cfg.get("style", "bars"))
    color_mode = str(cfg.get("color_mode", "gradient"))
    gap = GAPS.get(str(cfg.get("gap", "normal")), 3.0)
    margin = 6.0
    floor = 2.0 if bool(cfg.get("show_floor", True)) else 0.0
    radius = {"square": "0", "soft": "1", "round": "50%"}.get(str(cfg.get("corners", "soft")), "1")

    top_pad = 8.0
    label_h = 18.0 if bool(cfg.get("show_label", False)) else 0.0
    bottom = 100.0 - margin - label_h
    usable_h = bottom - top_pad
    width = (100.0 - 2 * margin - gap * (n - 1)) / n

    state: Dict[str, Any] = {
        "b_w": pct(width),
        "b_r": radius,
        "label_h": pct(label_h),
        "label_y": pct(100.0 - margin - label_h),
        "label_c": (str(cfg.get("label_color") or "#ffffff") if label_h else "transparent"),
        "msg": error or "",
        "msg_c": "#ffb4b4" if error else "transparent",
    }

    for i in range(1, MAX_BARS + 1):
        if i > n:
            state[f"b{i}_x"] = "0%"
            state[f"b{i}_y"] = "0%"
            state[f"b{i}_h"] = "0%"
            state[f"b{i}_c"] = "transparent"
            continue
        level = values[i - 1] / 100.0
        h = max(floor, usable_h * level)
        x = margin + (i - 1) * (width + gap)
        if style == "center":
            y = top_pad + (usable_h - h) / 2.0
        elif style == "top":
            y = top_pad
        else:
            y = bottom - h
        state[f"b{i}_x"] = pct(x)
        state[f"b{i}_y"] = pct(y)
        state[f"b{i}_h"] = pct(h)
        state[f"b{i}_c"] = bar_color(color_mode, cfg, i - 1, n, level)
    return state


# ── Render-time values ───────────────────────────────────────────────────────

RENDER_WINDOW_S = 0.02   # one cava read serves every key of one render


class LiveFace:
    """Everything one button needs to draw itself, computed lazily per render."""

    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = dict(cfg)
        self.bars = cfg_int(cfg, "bars", 12, 2, MAX_BARS)
        self.sensitivity = cfg_int(cfg, "sensitivity", 100, 10, 1000)
        self.method = str(cfg.get("source", "auto"))
        self.mode = str(cfg.get("response", "peak"))
        self._lock = threading.Lock()
        self._at = 0.0
        self._state: Dict[str, Any] = face_state(self.cfg, [0] * self.bars, None)

    def current(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._at >= RENDER_WINDOW_S:
                values, error = get_frame(
                    self.bars, self.method, self.sensitivity, 30, self.mode,
                )
                self._state = face_state(self.cfg, values, error)
                self._at = now
            return self._state


class LiveKey:
    """A state value resolved at render time -- ``str()`` reads the live face."""

    __slots__ = ("face", "key")

    def __init__(self, face: LiveFace, key: str) -> None:
        self.face = face
        self.key = key

    def __str__(self) -> str:
        return str(self.face.current().get(self.key, ""))

    __repr__ = __str__


def live_state(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """State for a button: one :class:`LiveKey` per render key."""
    face = LiveFace(cfg)
    return {key: LiveKey(face, key) for key in face.current()}
