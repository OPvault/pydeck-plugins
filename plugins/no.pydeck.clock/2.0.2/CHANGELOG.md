## 2.0.2 — 2026-04-15

### Changed

- Restructured onto the current PDK layout — `src/functions/<name>/` holding a `template.xml` and `handler.py` per function, plus `assets/` and `meta/` — replacing the root `plugin.xml` and flat `plugin.py`.
- Re-homed under the RDNN id `no.pydeck.clock`, so the install directory is `~/.local/share/pydeck/plugin/no.pydeck.clock/` instead of a bare `clock/`.

## 2.0.1 — 2026-04-12

### Fixed

- Reduced the seconds font size so the full time fits the face instead of the trailing digits being clipped.

## 2.0.0 — 2026-04-12

### Changed

- First PDK release: the face moved from Pillow drawing inside `plugin.py` to an XML template rendered by the core, so the clock now follows the same styling cascade as every other button.
- Requires PyDeck 1.1.0 or newer.
- The single `show_clock` action became a `clock` function with real options.

### Added

- A timezone picker with 43 zones, so a button can show somewhere other than local time.
- Separate toggles for seconds, 12-hour time and the date.

## 1.1.0 — 2026-04-06

### Removed

- The horizontal/vertical style choice, in favour of a single layout that the later PDK rewrite would replace outright.

### Changed

- Trimmed the declared permissions down to what the plugin actually imports, dropping `pathlib` and `hashlib`.

## 1.0.1 — 2026-04-06

### Fixed

- Hid the image gallery for the clock function. The clock draws its own face, so a user-picked icon was silently painted over on the next tick.

## 1.0.0 — 2026-04-03

### Added

- First release published to the marketplace: a live digital clock rendered straight onto the button and updated every second, in a Clean or Sketchy style.

## 0.2.0-beta — 2026-03-30

### Changed

- Moved to the V2 plugin layout as `plugins/plugin/clock/`, with its own `manifest.json`, `plugin.py` and `options.json`.
- Became the first plugin to redraw its own face on a timer, which is what the display-poll loop was built for.

## 0.1.0-beta — 2026-03-15

### Added

- Born as `pydeck/modules/clock.py` in the first pluggable module system — 183 lines that rendered a clock straight to the key image.
