## 2.0.9 — 2026-08-30

### Fixed

- The track label on the now-playing face was clipped off the bottom edge on
  an 80 px Mini key and pushed clean off the face on a 96 px XL. The overlay
  was a normal flow child pulled back over the album art with a `gap: -72`,
  and PDK resolves a bare pixel value against nothing — it does not scale with
  the key, so the offset only ever lined up on a 72 px key, and was out by
  twice as much again in the 2x web preview. The overlay is now
  `position: absolute` at 100%/100%, which pins it to the art on every deck.
