## 0.1.0 — 2026-08-30

### Added

- **Launch Game** key: pick any installed Steam game from a searchable dropdown
  and press to start it. Steam is started first when it isn't running, so a
  cold press still ends up in-game.
- The key face is the game's icon by default (the same one Steam shows in
  its library sidebar, stretched to fill the key), the logo Steam overlays on the library banner,
  or its library poster — both taken straight from the
  Steam client's own image cache (`appcache/librarycache`), no network, no
  API key. Games with nothing cached fall back to a name-on-dark face.
- Optional title overlay, plus a short "Launching…" flash after a press.
- Games are read from every library folder in `libraryfolders.vdf`, with
  Proton, runtimes and redistributables filtered out of the list.
