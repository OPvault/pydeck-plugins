## 0.1.0 — 2026-08-30

### Added

- First release. A `spectrum` key that runs `cava` in raw output mode in the
  background and draws its bars on the face. The bars are read at render time
  and the face rides PyDeck's animation tick, so it moves at ~15 fps on the
  deck and ~5 fps in the browser instead of being tied to the poll interval.
- Layouts: bars rising from the bottom, hanging from the top, or mirrored
  around the middle; 4 to 32 bars with adjustable gap and corner shape.
- Colour modes: solid, a quiet→loud gradient, a colour spread across the bars,
  or a rainbow. The key background follows the button colour or gradient.
- Audio input selection (auto, PipeWire, PulseAudio, ALSA), sensitivity, and
  peak / average / latest response.
- cava stops itself after 20 s without a render and dies with PyDeck, so an
  unused profile or a restart never leaves a capture running.
