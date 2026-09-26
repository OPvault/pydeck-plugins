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
import json
import os
import re
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
RETRY_S = 5.0               # wait this long before restarting a failed cava
FEED_REAP_S = 2.0           # stop a feed nothing has read for this long


def cava_path() -> Optional[str]:
    return shutil.which("cava")


def _child_env() -> Dict[str, str]:
    """cava's environment, with the runtime dir put back if PyDeck has none.

    PulseAudio's client library looks for its socket at
    ``$XDG_RUNTIME_DIR/pulse/native`` and nowhere else, and PipeWire's
    pulse interface is served from the same place. PyDeck's installer writes
    a systemd *system* unit (``WantedBy=multi-user.target`` with ``User=``),
    and a system unit is started with no session environment at all -- no
    XDG_RUNTIME_DIR, no bus address -- so cava cannot find the socket and
    quits with "check if pulseaudio is running" before its first frame.

    ``/run/user/<uid>`` is where logind puts that directory, so pointing at it
    is exactly what the missing session would have done. Only ever filled in,
    never overridden: a session that set it knows better than we do.
    """
    env = dict(os.environ)
    if not env.get("XDG_RUNTIME_DIR"):
        runtime_dir = f"/run/user/{os.getuid()}"
        if os.path.isdir(runtime_dir):
            env["XDG_RUNTIME_DIR"] = runtime_dir
    return env


# ── Audio devices ────────────────────────────────────────────────────────────
#
# With no ``source`` in its config cava captures whatever the input method
# considers the default, which on a desktop that splits its audio is the wrong
# line: a GoXLR gives Game, Music, Chat, System and Sample a sink each, and
# only one of them carries the track. So the source is made a setting, and the
# choices are read off the machine rather than typed.
#
# The PulseAudio and the PipeWire inputs both take a source *name*, and a
# sink's monitor has the same name for both -- ``method = pipewire`` with
# ``source = …Line2__sink.monitor`` captures that sink and nothing else -- so
# one listing serves pulse, pipewire and ``auto`` alike. ALSA is the odd one
# out: its input wants a ``hw:`` device, which is why the picker is scoped by
# the chosen method.

SOURCES_TTL_S = 10.0        # how long one device listing is reused


_SOURCES_LOCK = threading.Lock()
_SOURCES_CACHE: Dict[str, Tuple[float, List[Dict[str, str]]]] = {}


def _run_tool(cmd: List[str], timeout: float = 3.0) -> Optional[str]:
    """stdout of a short-lived helper, or None if it did not run cleanly."""
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            env=_child_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def _pulse_entry(
    name: str, description: str, monitor_of: str, default_sink: str,
) -> Dict[str, str]:
    """One picker row, named the way the desktop names it.

    A monitor is what a visualiser almost always wants, so it is labelled by
    the sink it listens to -- "Monitor of GoXLRMini Music" reads as
    "GoXLRMini Music (output)" -- and the one behind the system default is
    marked, since that is what *Auto* would have picked.
    """
    is_monitor = bool(monitor_of) or name.endswith(".monitor")
    label = (description or name).strip()
    if is_monitor:
        if label[:11].lower() == "monitor of ":
            label = label[11:].strip()
        label = f"{label} (output)"
        if monitor_of and monitor_of == default_sink:
            label = f"{label} · default"
    else:
        label = f"{label} (input)"
    return {"value": name, "label": label, "kind": "output" if is_monitor else "input"}


def _default_sink(exe: str) -> str:
    """The sink the desktop sends audio to unless told otherwise, briefly cached."""
    now = time.monotonic()
    with _SOURCES_LOCK:
        stamp, cached = _SOURCES_CACHE.get("default", (0.0, []))
        if cached and now - stamp < SOURCES_TTL_S:
            return cached[0]["value"]
    name = (_run_tool([exe, "get-default-sink"]) or "").strip()
    with _SOURCES_LOCK:
        _SOURCES_CACHE["default"] = (now, [{"value": name, "label": name, "kind": "sink"}])
    return name


def _pulse_sources() -> List[Dict[str, str]]:
    """Every PulseAudio/PipeWire source, monitors first."""
    exe = shutil.which("pactl")
    if exe is None:
        return []
    default_sink = _default_sink(exe)
    entries: List[Dict[str, str]] = []
    parsed: Any = None
    out = _run_tool([exe, "-f", "json", "list", "sources"])
    if out:
        try:
            parsed = json.loads(out)
        except ValueError:
            parsed = None
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if not name or name.startswith("auto_null"):
                continue
            entries.append(_pulse_entry(
                name,
                str(item.get("description") or name),
                str(item.get("monitor_source") or ""),
                default_sink,
            ))
    else:
        # pactl before 16 has no JSON formatter. Its short listing is
        # tab-separated and carries the name but no description, which still
        # names the device well enough to pick from.
        for line in (_run_tool([exe, "list", "sources", "short"]) or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 2 or not parts[1] or parts[1].startswith("auto_null"):
                continue
            entries.append(_pulse_entry(parts[1], parts[1], "", default_sink))
    entries.sort(key=lambda e: (e["kind"] != "output", e["label"].lower()))
    return entries


def _alsa_card_names() -> Dict[int, str]:
    """Card number → its short id, e.g. ``{3: "GoXLRMini"}``."""
    cards: Dict[int, str] = {}
    try:
        with open("/proc/asound/cards", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                # " 3 [GoXLRMini      ]: USB-Audio - GoXLRMini"
                head, sep, _rest = line.partition("]:")
                if not sep or "[" not in head:
                    continue
                number, _, ident = head.partition("[")
                try:
                    cards[int(number.strip())] = ident.strip()
                except ValueError:
                    continue
    except OSError:
        pass
    return cards


def _alsa_sources() -> List[Dict[str, str]]:
    """Capture-capable ALSA PCMs, spelled the way cava's alsa input wants.

    ``hw:<card id>,<device>`` rather than the card *number*, because the number
    is whatever order the kernel enumerated the cards in this boot.
    """
    cards = _alsa_card_names()
    entries: List[Dict[str, str]] = []
    try:
        with open("/proc/asound/pcm", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                # "03-00: USB Audio : USB Audio : playback 1 : capture 1"
                fields = [f.strip() for f in line.split(":")]
                if len(fields) < 3 or "capture" not in ":".join(fields[3:]):
                    continue
                card_no, _, dev_no = fields[0].partition("-")
                try:
                    card_i, dev_i = int(card_no), int(dev_no)
                except ValueError:
                    continue
                ident = cards.get(card_i) or str(card_i)
                value = f"hw:{ident},{dev_i}"
                entries.append({
                    "value": value,
                    "label": f"{ident} — {fields[1]} ({value})",
                    "kind": "input",
                })
    except OSError:
        return []
    return entries


def list_sources(method: str = "auto") -> List[Dict[str, str]]:
    """The devices this input method's ``source`` accepts, briefly cached.

    Both the editor and every starting feed ask for this, so a listing is
    reused for a few seconds rather than spawning a ``pactl`` per call.
    """
    kind = "alsa" if method == "alsa" else "pulse"
    now = time.monotonic()
    with _SOURCES_LOCK:
        stamp, cached = _SOURCES_CACHE.get(kind, (0.0, []))
        if cached and now - stamp < SOURCES_TTL_S:
            return list(cached)
    entries = _alsa_sources() if kind == "alsa" else _pulse_sources()
    with _SOURCES_LOCK:
        _SOURCES_CACHE[kind] = (now, entries)
    return list(entries)


def source_present(name: str, method: str) -> Optional[bool]:
    """Whether that device is here — None when the listing could not be read.

    The third answer matters: PyDeck may be running somewhere ``pactl`` is not
    installed or cannot reach the session, and "I cannot tell" must not be
    turned into "your device is gone".
    """
    entries = list_sources(method)
    if not entries:
        return None
    return any(e["value"] == name for e in entries)


def api_sources(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """Options for the *Audio source* picker.

    Reached at ``GET /api/plugins/no.pydeck.cava/api/sources``, scoped by the
    input method the button is on, which the editor forwards as ``?method=``.
    The empty first entry puts the picker back to whatever cava would have
    chosen on its own.
    """
    method = str(config.get("method") or "auto")
    return [{"label": "Auto — follow whatever is playing", "value": ""}] + [
        {"label": e["label"], "value": e["value"]} for e in list_sources(method)
    ]


# ── Following the audio ──────────────────────────────────────────────────────
#
# *Auto* used to mean "whatever cava picks", which is the default sink and
# nothing else. On a split setup that is usually the wrong line: the desktop's
# default carries system sounds while the music plays on its own sink, so the
# key sat flat with a track running.
#
# So Auto now hunts. While the chosen line has sound it is left alone; once it
# has been silent for a couple of seconds the picker steps to the next sink
# that has a stream open on it, and keeps stepping until one is audible. The
# stepping matters more than picking a favourite: a stream being open says
# nothing about it making noise -- speech-dispatcher holds an uncorked stream
# on the chat sink forever and is silent every second of it -- and a picker
# that always chose the "best" candidate would sit on that stream for good.
# A ring visits each in turn instead, so silence is self-correcting.
#
# The default sink's monitor is always the first entry and always the last, so
# a machine with nothing playing anywhere settles on it, which is what cava
# would have done unaided.

AUTO_SILENCE_S = 2.5        # silent this long before Auto looks elsewhere
AUTO_STEP_S = 2.0           # and this long on each line it tries

_AUTO_LOCK = threading.Lock()
# input method → [source, decided at, last heard at]. Module level, and
# mutable, because it has to outlive a face: see auto_heard().
_AUTO: Dict[str, List[Any]] = {}


def _sink_monitors(exe: str) -> Tuple[Dict[Any, str], Dict[str, str]]:
    """``{sink index or name: monitor source}`` and ``{sink name: state}``."""
    out = _run_tool([exe, "-f", "json", "list", "sinks"])
    monitors: Dict[Any, str] = {}
    states: Dict[str, str] = {}
    if not out:
        return monitors, states
    try:
        parsed = json.loads(out)
    except ValueError:
        return monitors, states
    if not isinstance(parsed, list):
        return monitors, states
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        monitor = str(item.get("monitor_source") or (f"{name}.monitor" if name else ""))
        if not monitor:
            continue
        states[name] = str(item.get("state") or "")
        monitors[name] = monitor
        # pactl names the sink of a stream by index, not by name, so both
        # spellings are kept and either one resolves.
        if item.get("index") is not None:
            monitors[item["index"]] = monitor
    return monitors, states


def _playing_monitors(exe: str, monitors: Dict[Any, str]) -> List[str]:
    """Monitors of the sinks with a stream open on them, newest stream first.

    Newest first only decides where the ring *starts*; a corked stream is
    skipped outright, since a paused player is not something to watch.
    """
    out = _run_tool([exe, "-f", "json", "list", "sink-inputs"])
    ranked: List[Tuple[int, str]] = []
    if not out:
        return []
    try:
        parsed = json.loads(out)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        corked = item.get("corked")
        if corked is True or str(corked).lower() == "yes" or str(corked).lower() == "true":
            continue
        monitor = monitors.get(item.get("sink")) or monitors.get(str(item.get("sink")))
        if not monitor:
            continue
        try:
            index = int(item.get("index") or 0)
        except (TypeError, ValueError):
            index = 0
        ranked.append((index, monitor))
    ranked.sort(reverse=True)
    seen: List[str] = []
    for _index, monitor in ranked:
        if monitor not in seen:
            seen.append(monitor)
    return seen


def auto_candidates() -> List[str]:
    """The lines *Auto* will cycle through, best guess first.

    The default sink's monitor bookends the ring: first when it is one of the
    ones playing, last always, so it is both the obvious opening guess and the
    place a silent machine comes to rest.
    """
    exe = shutil.which("pactl")
    if exe is None:
        return []
    default_monitor = ""
    monitors, states = _sink_monitors(exe)
    default_sink = _default_sink(exe)
    if default_sink:
        default_monitor = monitors.get(default_sink) or f"{default_sink}.monitor"
    playing = _playing_monitors(exe, monitors)
    if not playing:
        # No stream anywhere, or no way to read the stream list. Fall back to
        # the sinks the server itself calls running before giving up on the
        # default, which is all an older pactl leaves to go on.
        playing = [monitors[n] for n, st in states.items() if st == "RUNNING" and n in monitors]
    ring: List[str] = []
    for candidate in ([default_monitor] if default_monitor in playing else []) + playing + [default_monitor]:
        if candidate and candidate not in ring and not candidate.startswith("auto_null"):
            ring.append(candidate)
    return ring


def auto_source(method: str) -> str:
    """The device *Auto* should be listening to this instant.

    An empty return means "no idea" and leaves the choice to cava, which is the
    right answer when there is no ``pactl`` to ask.
    """
    if method == "alsa":
        # Nothing in ALSA says which device is busy, and its names are not
        # interchangeable with the others'. Leave it to cava.
        return ""
    now = time.monotonic()
    with _AUTO_LOCK:
        state = _AUTO.get(method)
        if state:
            source, decided_at, heard_at = state
            if now - heard_at < AUTO_SILENCE_S:
                return source                  # audible: do not go looking
            if now - decided_at < AUTO_STEP_S:
                return source                  # give this one its turn first
    ring = auto_candidates()
    if not ring:
        return ""
    with _AUTO_LOCK:
        state = _AUTO.get(method)
        current = state[0] if state else ""
        try:
            nxt = ring[(ring.index(current) + 1) % len(ring)]
        except ValueError:
            # Either the first pick of all, or the line we were on has stopped
            # being a candidate -- its player quit or paused -- in which case
            # the front of the ring is a better guess than the one after it.
            nxt = ring[0]
        # A new choice starts audible on paper, so it gets the full silence
        # window to produce something rather than being judged on the frames
        # cava had not made yet.
        _AUTO[method] = [nxt, now, now]
    return nxt


def auto_heard(method: str, source: str, values: List[int]) -> None:
    """Report what *Auto*'s current choice just produced.

    The silence clock lives here, beside the choice, and not on the face that
    reads the frames. PyDeck builds a fresh face on every poll -- once a second
    -- so a timer owned by one is reset a second after it starts and can never
    reach a threshold measured in seconds. That is precisely what made Auto
    lock onto the first line it found and never let go.
    """
    if method == "alsa" or not source or not any(values):
        return
    now = time.monotonic()
    with _AUTO_LOCK:
        state = _AUTO.get(method)
        if state and state[0] == source:
            state[2] = now


# ── cava process ─────────────────────────────────────────────────────────────

class _Feed:
    """One running cava process and the frames it has produced."""

    def __init__(
        self, bars: int, method: str, source: str, sensitivity: int, framerate: int,
    ) -> None:
        self.bars = bars
        self.method = method
        self.source = source
        self.sensitivity = sensitivity
        self.framerate = framerate
        self.key = (bars, method, source, sensitivity, framerate)

        self._lock = threading.Lock()
        self._pending: List[List[int]] = []
        self._latest: List[int] = [0] * bars
        self._latest_at = 0.0
        self._last_request = time.monotonic()
        self._proc: Optional[subprocess.Popen] = None
        self._config_path: Optional[str] = None
        self._error: Optional[str] = None
        self._stopped = False
        # The method actually passed to cava: the configured one, unless a
        # previous feed already found that this build has no such input.
        self._method_used = "auto" if method in _UNSUPPORTED_INPUTS else method
        self._frames = 0
        self._stderr: List[str] = []
        self._started_at = 0.0

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self._started_at = time.monotonic()
        exe = cava_path()
        if exe is None:
            self._error = "cava not found"
            return
        if self.source and source_present(self.source, self._method_used) is False:
            # cava does not object to a source that is not there. It starts,
            # captures nothing and prints zeros for as long as you leave it,
            # which on a key is indistinguishable from a quiet room -- so the
            # device is checked here and the key says what is wrong instead.
            self._error = "input missing"
            return
        # One file per setting *and per process*, overwritten on every start.
        # PyDeck runs the server and the deck listener as separate processes,
        # each with its own copy of this module and its own feed: on a shared
        # path, whichever one reads a frame first unlinks the file out from
        # under a cava the other is still starting, which cava reports as
        # "Unable to open file" and exit 1.
        path = os.path.join(
            tempfile.gettempdir(),
            f"pydeck-cava-{os.getuid()}-{os.getpid()}"
            f"-{self.bars}-{self._method_used}-{_path_tag(self.source)}"
            f"-{self.sensitivity}-{self.framerate}.conf",
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._config_text())
        self._config_path = path
        self._frames = 0
        self._stderr = []
        try:
            self._proc = subprocess.Popen(
                [exe, "-p", path],
                stdout=subprocess.PIPE,
                # cava explains itself here -- which input it lacks, that it
                # cannot reach pulseaudio -- and discarding it left the face
                # with nothing to report but an exit code.
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=0,
                preexec_fn=_die_with_parent,
                env=_child_env(),
            )
        except OSError as exc:
            self._error = f"cava failed: {exc}"
            self._cleanup_config()
            return
        threading.Thread(target=self._reader, name="pydeck-cava", daemon=True).start()
        threading.Thread(target=self._stderr_reader, name="pydeck-cava-err", daemon=True).start()
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
        # Both keys are optional and independent: a source with no method is
        # cava's own pick of input pointed at a device of ours, which is what
        # the *Auto* input method plus a chosen source has to mean.
        input_lines = []
        if self._method_used != "auto":
            input_lines.append(f"method = {self._method_used}")
        if self.source:
            input_lines.append(f"source = {self.source}")
        if input_lines:
            lines += ["[input]"] + input_lines
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
                self._frames += 1
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
                missing = _missing_input(self._stderr)
                if missing and self._frames == 0:
                    # Not a failure the user can do anything about: this build
                    # simply has no such input. Remember it and leave _error
                    # unset -- the next render builds a feed that starts on the
                    # default input, one wasted process per PyDeck process.
                    _UNSUPPORTED_INPUTS.add(missing)
                else:
                    self._error = _short_error(proc.returncode, self._stderr)

    def _stderr_reader(self) -> None:
        """Keep the last few lines cava wrote, to explain a failed start."""
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self._stderr.append(line)
                    del self._stderr[:-5]
        except (OSError, ValueError):
            pass

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


# What cava says on the way out, in the few characters a key can show. The
# face draws this at 0.65em across the full width, which is about sixteen
# characters -- so the full line is worth matching on, and worth nothing to
# print. Anything unrecognised falls back to the exit code, which is at least
# a number the DOCS can explain.
_MISSING_INPUT_RE = re.compile(r"built without '(\w+)' input")

_ERROR_PATTERNS = (
    (_MISSING_INPUT_RE, lambda m: f"no {m.group(1)} input"),
    (re.compile(r"snd_aloop"), lambda m: "no alsa loopback"),
    (re.compile(r"pulseaudio", re.I), lambda m: "no pulseaudio"),
    (re.compile(r"pipewire", re.I), lambda m: "no pipewire"),
    (re.compile(r"Unable to open file"), lambda m: "config missing"),
    (re.compile(r"[Nn]o such device|cannot open audio"), lambda m: "no audio device"),
)


def _missing_input(stderr_lines: List[str]) -> Optional[str]:
    """The input cava says it has no support for, if that is why it quit."""
    for line in reversed(stderr_lines):
        m = _MISSING_INPUT_RE.search(line)
        if m:
            return m.group(1)
    return None


def _short_error(returncode: Optional[int], stderr_lines: List[str]) -> str:
    """A key-sized reason for a cava that would not run."""
    for line in reversed(stderr_lines):
        for pattern, render in _ERROR_PATTERNS:
            m = pattern.search(line)
            if m:
                return render(m)
    return f"cava exited ({returncode})"


def _path_tag(source: str) -> str:
    """The source as a filename fragment.

    The *tail* is what tells two devices apart -- ``…Line1__sink.monitor`` and
    ``…Line2__sink.monitor`` agree for their first fifty characters -- so it is
    the end that survives the truncation, not the beginning.
    """
    if not source:
        return "auto"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", source)[-64:]


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
_FEEDS: Dict[Tuple[int, str, str, int, int], _Feed] = {}

# Inputs cava told us it was not compiled with. cava only has the inputs its
# packager built in -- pipewire is missing from several distributions' builds,
# including Fedora's -- and it refuses to start at all on one it lacks. The
# first refusal is remembered here, so the next feed for that setting comes up
# on the build's own default input instead of the key staying dead.
_UNSUPPORTED_INPUTS: set = set()


def get_frame(
    bars: int, method: str, source: str, sensitivity: int, framerate: int, mode: str,
) -> Tuple[List[int], Optional[str]]:
    """Return the current spectrum for this configuration, starting cava if needed."""
    key = (bars, method, source, sensitivity, framerate)
    with _FEED_LOCK:
        feed = _FEEDS.get(key)
        if feed is None or not feed.alive:
            if feed is not None and feed._error and not feed._stopped:
                # Failed start: report, but retry only every few seconds so a
                # missing binary does not spawn a process per poll.
                #
                # Measured from the attempt, not from the last frame request:
                # _last_request is refreshed by every render, fifteen times a
                # second, so a gate on it never opened at all and one failed
                # start stuck to the key until PyDeck was restarted.
                if time.monotonic() - feed._started_at < RETRY_S:
                    return feed.frame(mode)
            feed = _Feed(bars, method, source, sensitivity, framerate)
            feed.start()
            _FEEDS[key] = feed
        # Drop feeds for configurations no button uses any more. A live one
        # is stopped rather than left to its watchdog: when Auto steps from
        # line to line, twenty seconds of grace each would stack up a cava per
        # candidate for something no face is reading.
        now = time.monotonic()
        for k in list(_FEEDS):
            if k == key:
                continue
            other = _FEEDS[k]
            if not other.alive:
                del _FEEDS[k]
            elif now - other._last_request > FEED_REAP_S:
                other.stop()
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
        self.device = str(cfg.get("device") or "").strip()
        self.mode = str(cfg.get("response", "peak"))
        self._lock = threading.Lock()
        self._at = 0.0
        self._state: Dict[str, Any] = face_state(self.cfg, [0] * self.bars, None)

    def current(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._at >= RENDER_WINDOW_S:
                source = self.device or auto_source(self.method)
                values, error = get_frame(
                    self.bars, self.method, source, self.sensitivity, 30, self.mode,
                )
                if not self.device:
                    auto_heard(self.method, source, values)
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
