## 2.0.0 — 2026-08-22

### Changed

- Rewritten on the PDK 2.x layout under the RDNN id `no.pydeck.home-assistant`, with separate display and toggle handlers under `src/functions/`.
- Entity icons are resolved from the Material Design Icon set the entity itself declares, rather than a fixed per-domain image.

### Added

- Bundled DOCS.md, shown right after install, covering the long-lived access token and the base URL format.

## 1.1.1 — 2026-04-06

### Fixed

- Runtime-generated Material Design Icon PNGs moved from the plugin's own directory to `plugins/storage/home-assistant/`, so they survive a plugin update instead of being wiped along with the install directory.

## 1.1.0 — 2026-04-06

### Added

- A domain filter in the entity picker: choose a domain first, then an entity. The old flat list showed every entity in the house at once, which is unusable past a few dozen.

## 1.0.1 — 2026-04-03

### Fixed

- The toggle-switch icon never appeared on switch entities. The image path was hardcoded to the old `ha` directory name and broke as soon as the plugin was installed under its catalog slug; it now derives the path from the install directory.
- A URL with no port defaults to 8123 rather than failing with connection refused, which is what happened to anyone who typed a bare IP address.

## 1.0.0 — 2026-04-03

### Added

- First release published to the marketplace, renamed from `ha` to `home-assistant`: toggle any entity and display any entity's state on a button.

## 0.2.0-beta — 2026-03-29

### Changed

- Moved to the V2 plugin layout as `plugins/plugin/ha/`, with the entity picker driven by an `api_select` dropdown fed from the plugin's own API endpoint.

## 0.1.0-beta — 2026-03-15

### Added

- In PyDeck's very first commit, as `pydeck/ha.py` — Home Assistant was built into the app before any plugin system existed.
- Rewritten the same day as `pydeck/modules/ha.py`, at 415 lines the largest module of the original set.
