## 2.0.1 — 2026-04-15

### Changed

- Restructured onto the current PDK layout — `src/functions/<name>/` with `meta/` — replacing the root `plugin.xml` and flat `plugin.py`.
- Re-homed under the RDNN id `no.pydeck.weather`, completing the rename from MET.

## 2.0.0 — 2026-04-12

### Changed

- First PDK release, and the rename from MET to Weather: the face moved to XML templates rendered by the core.
- The two functions were rebuilt as Current Weather and Multiple Forecasts, polling every 60 seconds — met.no's data does not change faster than that.

### Added

- Kelvin joined Celsius and Fahrenheit as a temperature unit.
- A dynamic background that follows the current conditions.
- A display mode for the forecast, showing times, days or condition icons.

## 1.1.2 — 2026-04-06

### Added

- A description for the bundled met.no licence, so the marketplace can say what it covers.

## 1.1.1 — 2026-04-06

### Added

- Bundled the met.no licence with the plugin.

## 1.1.0 — 2026-04-05

### Added

- A Multiple Forecasts function showing three temperatures for the same place at a chosen interval — 1, 3, 6, 12 or 24 hours — turning one button into a short forecast.
- Temperature rounding (none, down, up or nearest) and an optional unit suffix.

### Changed

- The original function was relabelled from "MET" to "Current Temperature", now that there are two.

## 1.0.0 — 2026-04-03

### Added

- First release as the MET plugin: current weather for a named location from met.no's public API, with no API key required.
