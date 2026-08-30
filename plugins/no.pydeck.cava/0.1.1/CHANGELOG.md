## 0.1.1 — 2026-08-30

### Fixed

- A key set to an input its cava was not built with went dead with nothing to
  show but `cava exited (1)`. cava only has the inputs its packager compiled
  in — Fedora's build has no PipeWire input, Arch's does — and it refuses to
  start at all on one it lacks. The first refusal is now remembered and the
  key comes up on the build's own default input instead.
- Nothing worked at all when PyDeck runs as a systemd *system* service, which
  is what its own installer writes. A system unit is started with no session
  environment, and PulseAudio's client library finds its socket at
  `$XDG_RUNTIME_DIR/pulse/native` and nowhere else — so cava quit with "check
  if pulseaudio is running" before its first frame, on a desktop where audio
  was plainly working. cava is now given `/run/user/<uid>` when the variable
  is absent, which is what the missing session would have set. An environment
  that already has one is never overridden.
- A cava that failed to start was never retried. The five-second gate measured
  from the last *frame request*, which the animation tick refreshes fifteen
  times a second, so it never opened: one failed start — a wrong input, or
  PyDeck launching before the audio stack was up — stuck to the key until
  PyDeck itself was restarted. It now measures from the last attempt, and a
  failed feed is retried every five seconds as intended.
- The face said what cava's exit code was, never what cava said, because
  stderr went to `/dev/null`. It is now read and turned into something that
  fits a key: `no pipewire input`, `no pulseaudio`, `no alsa loopback`, with
  the exit code as the fallback for anything unrecognised.
- Two PyDeck processes (the server and the deck listener) each run their own
  feed and were writing one config file at one shared path. Whichever read a
  frame first deleted it, which could leave the other's cava starting on a
  file that had just vanished — `Unable to open file`, exit 1. The path now
  carries the process id.
