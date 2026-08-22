## 2.0.0 — 2026-08-22

### Changed

- Rewritten on the PDK 2.x layout under the RDNN id `no.pydeck.media-control`.
- Split into eight single-purpose functions — Play, Pause, Play/Pause, Next Track, Previous Track, Volume Up, Volume Down and Toggle Mute — so a transport row can be laid out exactly as you want it rather than cycling one button.

### Added

- A player field on every function, so a button can be pointed at one specific MPRIS player instead of whatever happens to be active.
- Play/Pause can show the current track as its label, and polls every 2 seconds to keep it current.
- Volume Up and Volume Down take a step percentage, and can show the resulting volume on the button.

## 1.0.0 — 2026-04-03

### Added

- First release published to the marketplace, packaged out of the pydeck core repo.

### Changed

- Slug renamed from `media_control` to `media-control` to match the marketplace's kebab-case convention.

## 0.1.0-beta — 2026-03-28

### Added

- Born directly in the V2 plugin layout as `plugins/plugin/media_control/`, shipping with a set of ready-made button profiles.
