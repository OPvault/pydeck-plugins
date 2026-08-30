## 1.0.0 — 2026-08-30

### Added

- First release. A decorative key that shows the button's own picture or GIF
  behind up to three lines of text and does nothing at all when pressed.
- Everything on the face comes from the button rather than from handler state:
  its image, its colour or gradient, its three label rows, and the per-row text
  styles set in the editor. PDK shares handler state between every button
  running the same function, so anything routed through it would leave two
  showcase buttons showing one picture.
- No `on_press`, `on_release` or `on_poll` handler, so the core never
  dispatches an event for these buttons and they cost nothing between renders.
