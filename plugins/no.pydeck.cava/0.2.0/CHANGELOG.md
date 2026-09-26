## 0.2.0 — 2026-09-20

### Added

- **Audio source** picker. cava with no `source` captures whatever its input
  method calls the default, which is the wrong line on any desktop that splits
  its audio — a GoXLR gives Game, Music, Chat, System and Sample a sink each,
  and only one of them carries the track, so the key sat flat while music was
  plainly playing. The Audio group now lists the machine's own devices by the
  names the desktop uses (*GoXLRMini Music (output)*), marks the one behind the
  system default, and puts the outputs first, since a monitor is what a
  visualiser wants.

  The list follows the input method: PipeWire, PulseAudio and *Auto* share one
  set of source names — a sink's monitor is the same string to all three — while
  *ALSA* lists `hw:` capture devices instead, which is the only spelling its
  input understands.

### Changed

- **Auto now follows the audio** rather than meaning "whatever cava picks",
  which was the system default and nothing else. Its candidates are the sinks
  with a stream open on them, newest first, with the default sink's monitor at
  the front when it is among them and at the back regardless. It leaves the
  chosen line alone for as long as that line has sound, and after about two and
  a half seconds of silence steps to the next candidate — two seconds each —
  until one is audible. Nothing playing anywhere leaves only the default, which
  is where a quiet machine settles.

  It steps rather than choosing the most promising candidate because a stream
  being *open* says nothing about it making noise: `speech-dispatcher` holds an
  uncorked stream on the chat sink permanently and is silent every second of
  it, and a key that picked the best-looking line would sit on that stream for
  good. Taking each in turn is what makes the silence self-correcting. Corked
  streams are skipped, so a paused player does not hold the key hostage either.

- A line Auto has moved off is now stopped within a couple of seconds instead
  of waiting out the twenty-second idle timer, so a search does not leave a
  cava running per candidate. This applies to any settings change, not just
  Auto's.

- The Audio group's **Input** setting is now labelled **Input method**, to keep
  it apart from the source picker beneath it.

### Fixed

- A device that is no longer there now says so. cava does not object to a
  source it cannot find: it starts, captures nothing and prints zeros for as
  long as you leave it, which on a key is indistinguishable from a quiet room.
  A configured source is checked against the live device list before cava is
  started, and the key shows `input missing` — but only when that list could
  actually be read, so a PyDeck with no way to reach the session is never told
  its device is gone.
