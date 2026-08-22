## 1.0.3 — 2026-08-22

### Changed

- Rewritten on the PDK 2.x layout under the RDNN id `no.pydeck.folders`, with a handler and template per function under `src/functions/`.
- Enter Folder, Return Folder and Switch Profile each keep their own face, so a folder button can show where it goes rather than a generic icon.

### Added

- Return Folder gained a mode control, choosing between stepping up one level and returning to the root in a single press.

## 1.0.2 — 2026-04-12

### Added

- Auto-return: a folder can close itself after a set number of seconds, so a folder opened for one press does not strand the deck on the wrong page.
- An optional countdown on the button while auto-return is pending, so the timeout is visible rather than surprising.

### Changed

- Auto-return settings persist at runtime, surviving a restart.

## 1.0.1 — 2026-04-05

### Added

- A Switch Profile action that jumps straight to a named profile from the deck, with the profile list supplied by the profiles API so it stays in sync as profiles are renamed.

## 1.0.0 — 2026-04-04

### Added

- First release published to the marketplace: Enter Folder and Return Folder, giving the deck more buttons than it has keys.

### Changed

- Renamed from `folder` to `folders` so the slug matches the plugin name.

## 0.2.0-beta — 2026-03-30

### Changed

- Moved to the V2 plugin layout as `plugins/plugin/folder/`, gaining breadcrumb navigation and a return action.

## 0.1.0-beta — 2026-03-15

### Added

- Born as `pydeck/modules/folder.py` in the first pluggable module system — the original answer to a deck having more actions than keys.
