## 2.0.4 — 2026-10-04

- Now requires PyDeck 2.0.0, which has the shared settings this version follows (Settings → Plugin settings → Shared by all plugins).
- Temperature unit has a new default, **Use global**: the key shows °C, °F or K as the shared setting says, so an American user sets °F once instead of on every key. A key set to C, F or K keeps it; switch it to Use global to follow the shared choice.
- Forecast hours follow the shared time format: `5PM` instead of `17` on a 12-hour clock. The rows step down one size to make room, as they already did for Kelvin.
- With No rounding, the decimal follows the shared separator (`12,5°`).
