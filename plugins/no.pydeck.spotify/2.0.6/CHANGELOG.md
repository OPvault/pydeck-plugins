## 2.0.6 — 2026-08-28

### Fixed

- The track label sat off-centre. A percentage width resolves against the parent box rather than its content box, so the horizontal padding on the row pushed every full-width child to the right; the inset is now vertical only.
- Dropped an invalid `text-anchor` declaration from the shared stylesheet, which the style cascade was parsing and discarding on every render.
