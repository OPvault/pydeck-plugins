## 2.0.3 — 2026-08-22

### Fixed

- Buttons went blank on the hardware while the web preview kept working. The listener process dispatches `on_poll` without credentials, so the plugin now reads `credentials.json` directly and treats the context as an overlay when it is there.
- Credentials are read from both the pre-RDNN `spotify` key and `no.pydeck.spotify`, RDNN last so a migrated entry wins over a stale one — an install that predates the RDNN move keeps working without re-authorising.
