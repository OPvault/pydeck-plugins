## 2.0.1 — 2026-04-15

### Changed

- Restructured onto the current PDK layout — `src/functions/<name>/` with `assets/` and `meta/` — replacing the root `plugin.xml` and flat `plugin.py`.
- Re-homed under the RDNN id `no.pydeck.f1`.
- The Jolpica F1 and OpenF1 licences moved to `meta/licenses/`, where the catalog picks them up for the marketplace's Licenses button.

## 2.0.0 — 2026-04-12

### Changed

- First PDK release: per-function XML templates replaced the flat `plugin.py` renderer, and the countdown poll dropped from 60 seconds to 1 so the clock actually ticks.
- The session checkboxes were reorganised into collapsible groups — sessions, countdown and display — instead of one long flat list.

### Added

- Driver Points gained its own display group, separating the standings figures from the headshot and styling controls.

## 1.0.3 — 2026-04-06

### Added

- Descriptions for each bundled licence, so the marketplace can explain what Jolpica and OpenF1 are actually used for rather than listing two opaque files.

## 1.0.2 — 2026-04-06

### Added

- Bundled the Jolpica F1 and OpenF1 licences with the plugin — Jolpica supplies the calendar, session times and standings, OpenF1 the circuit images and driver photos.

## 1.0.1 — 2026-04-06

### Changed

- Sprint Qualifying, Sprint Race and Qualifying now count toward the countdown by default. Only the main race did before, so on a sprint weekend the button counted past sessions that had already started.

## 1.0.0 — 2026-04-06

### Added

- First release: a countdown to the next Formula 1 race weekend, with per-session toggles for practice, qualifying, sprint and race.
