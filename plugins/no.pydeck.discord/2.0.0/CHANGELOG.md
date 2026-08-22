## 2.0.0 — 2026-08-22

### Changed

- Rewritten on the PDK 2.x layout under the RDNN id `no.pydeck.discord`: a `template.xml` and `handler.py` per function under `src/functions/`, replacing the flat `plugin.py` that drew the face with Pillow.
- Toggle Mute and Toggle Deafen now render their own state into the template, so the button reflects Discord rather than only sending to it.
- Voice state is still driven over Discord's local RPC socket — no bot token, no cloud round trip.

### Added

- Bundled DOCS.md, shown right after install, covering how to create the Discord application and where the client id and secret go.

## 1.1.4 — 2026-08-21

### Added

- Bundled DOCS.md, shown right after install.

## 1.1.3 — 2026-04-12

### Added

- Marked the voice functions `actionable`, so mute and deafen can be used as steps inside an Action Builder sequence.

## 1.1.2 — 2026-04-06

### Changed

- Renamed the action labels from "Discord Mute" and "Discord Deafen" to "Toggle Mute" and "Toggle Deafen" — they are toggles, and the sidebar already says Discord.

## 1.1.1 — 2026-04-06

### Fixed

- Toggling mute while deafened did nothing useful. It now sends `deaf: false` instead, mirroring Discord's own behaviour where the mute button acts as undeafen and clears both states at once.

## 1.1.0 — 2026-04-05

### Added

- `log_format` on every action, so the activity log reads as a sentence rather than a bare function name.

## 1.0.3 — 2026-04-04

### Fixed

- The OAuth redirect URI was a hardcoded module constant that fell out of sync whenever the server ran on a non-default port. It is now resolved from `lib.oauth` at import time, falling back to the constant when the core is unavailable.
- Wrapped AUTHENTICATE, the IPC queue timeout and every voice-settings call in error handling that closes the socket cleanly and reports a readable message, instead of leaving a half-open socket behind.

### Added

- A `user_agent` field in the manifest.

## 1.0.1 — 2026-04-04

### Added

- Background polling that refreshes the mute and deafen buttons every 10 seconds, so muting from inside Discord is reflected on the deck.
- Polling deliberately never triggers OAuth — it only runs once a token is already saved, so a fresh install does not pop an authorisation window on its own.

### Changed

- The last known state is tracked per credential pair, so an unchanged poll does not redraw the button.

## 1.0.0 — 2026-04-03

### Added

- First release published to the marketplace, packaged out of the pydeck core repo as a downloadable plugin rather than a folder shipped inside the app.

## 0.4.0-beta — 2026-04-03

### Changed

- Token management moved to the unified `credentials.json` store shared with every other plugin, instead of Discord keeping its own private token file.
- Credentials became editable from the settings overlay, with password fields that can be revealed on demand.

## 0.3.0-beta — 2026-03-28

### Added

- Display states: the mute and deafen buttons swap their image to reflect the current voice state instead of staying static.
- Sibling buttons update together, so muting from the mute button also refreshes the deafen button next to it.

## 0.2.0-beta — 2026-03-28

### Changed

- Rebuilt for the V2 plugin layout as `plugins/plugin/discord/` — 8 files and roughly 590 lines, exposing Discord Mute and Discord Deafen as real actions with a manifest rather than hardcoded buttons.

## 0.1.0-beta — 2026-03-15

### Added

- In PyDeck's very first commit, as `pydeck/discord_rpc.py` — Discord was built into the app before any plugin system existed.
- Rewritten the same day as `pydeck/modules/discord.py` (256 lines) when the app gained pluggable Python/JS action modules.

### Fixed

- The IPC socket is found by scanning every `/run/user/*/` directory rather than trusting `$XDG_RUNTIME_DIR`, which is unset when PyDeck runs as a systemd service; Flatpak and Snap socket paths were added as candidates.
- A press while Discord is not running is ignored quietly instead of surfacing an error in the web UI.
