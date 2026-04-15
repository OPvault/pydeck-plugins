## 2.0.1 — 2026-04-15

### Changed

- Restructured onto the current PDK layout — `src/functions/<name>/` with `assets/` and `meta/` — replacing the per-function `<fn>/<fn>.xml` pairs and flat `plugin.py`.
- Re-homed under the RDNN id `no.pydeck.spotify`, so the install directory is `~/.local/share/pydeck/plugin/no.pydeck.spotify/`.

## 2.0.0 — 2026-04-12

### Changed

- Complete rewrite on the PDK lifecycle — `on_load`, `on_poll` and `on_press` with `ctx.state`-driven templates and a handler per function, replacing the flat `plugin.py`. Requires PyDeck 1.1.0.
- Poll intervals were retuned per function now that they are independent: Play/Pause polls every second so the progress readout is smooth, the volume buttons every 3 seconds, and shuffle and repeat every 5.

## 1.1.2 — 2026-08-21

### Added

- Bundled DOCS.md, shown right after install.

## 1.1.1 — 2026-04-12

### Added

- A shared playback-state cache persisted to disk, so eight Spotify buttons poll the Web API once between them instead of eight times.
- Proper rate-limit handling: a 429 is retried after the `Retry-After` delay, capped so a long back-off cannot stall the poll loop.

### Fixed

- Redundant API calls were cut by reusing cached state, which is what pushed the plugin into rate limiting in the first place.

## 1.1.0 — 2026-04-05

### Added

- `log_format` on every action so the activity log reads as a sentence.

### Changed

- The OAuth redirect URI comes from `lib.oauth.get_redirect_uri`, staying in sync with the server's configured port.

## 1.0.4 — 2026-04-04

### Fixed

- The redirect URI was a hardcoded module constant; `SpotifyClient` now accepts one and falls back internally, so a server on a non-default port can still authorise.

## 1.0.3 — 2026-04-04

### Fixed

- The button kept showing the last track after Spotify went idle. On a 204 (no active device) it now resets to the default face, clears the label, and cancels the per-second countdown ticks queued while a track was still playing.
- An idle sentinel distinguishes "confirmed idle" from "never polled", so the reset fires on the first idle poll after a restart without re-sending on every poll after that.

## 1.0.2 — 2026-04-04

### Added

- A Show Time Left option, rendering the remaining track time as `-m:ss` above the label.
- It ticks once a second by preloading up to six display updates after each poll, so second-level resolution costs no extra API calls — the same trick the clock plugin uses.

### Changed

- The per-slot cache became a three-part record — art, label and time — so each field is dirty-checked on its own and only what actually changed is redrawn.

## 1.0.1 — 2026-04-03

### Fixed

- Album art is written to `plugins/storage/` instead of the plugin's own directory, so it survives a plugin update rather than being deleted with the install.

## 1.0.0 — 2026-04-03

### Added

- First release published to the marketplace, packaged out of the pydeck core repo as a downloadable plugin rather than a folder shipped inside the app.

## 0.4.0-beta — 2026-04-03

### Added

- A `sidebar_icon` per action, so the sidebar shows what each Spotify action does instead of a row of identical tiles.

### Changed

- Credentials moved into the shared store and became editable from the settings overlay, with the client secret masked and revealable.

## 0.3.0-beta — 2026-03-29

### Added

- Album art on the button: the artwork is downloaded from the playback state and cached as `_now_playing.jpg`, picking the smallest image at least 80px tall so the deck is not downloading 640px covers for a 72px key.
- A now-playing label with marquee scrolling for titles too long to fit.
- Per-action button icons for next, previous, shuffle, repeat and the volume keys.

### Changed

- The plugin caches the last art URL and label, so an unchanged poll does not re-download or redraw anything.

## 0.2.0-beta — 2026-03-28

### Changed

- Rebuilt for the V2 plugin layout as `plugins/plugin/spotify/` — 635 lines across `manifest.json`, `plugin.py`, `options.json` and a dedicated `spotify_client.py`.
- Shipped seven actions: Play/Pause, Next Track, Previous Track, Volume Up, Volume Down, Shuffle and Repeat.

## 0.1.0-beta — 2026-03-15

### Added

- In PyDeck's very first commit, as `pydeck/spotify.py` — Spotify was built into the app before any plugin system existed.
- Rewritten the same day as `pydeck/modules/spotify.py` (501 lines, the largest of the original modules): a 3-second playback poll, a marquee that steps 6 pixels every half second with a 40-pixel gap, and Spotify green `#1DB954` as the face colour.
- A configurable volume step from 1 to 100 percent for the Volume Up and Volume Down keys, shown as a stepper in the properties panel.
