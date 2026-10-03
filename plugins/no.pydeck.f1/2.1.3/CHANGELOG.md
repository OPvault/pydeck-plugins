## 2.1.3 — 2026-10-03

### Changed

- The Next Race key now names the circuit, not the nearest town: "Sepang"
  rather than "Kuala Lumpur", "Hungaroring" rather than "Budapest",
  "Yas Marina" rather than "Abu Dhabi". The name comes from the calendar's
  official circuit name with the filler stripped ("Sepang International
  Circuit" → "Sepang"), falling back to the circuit's id when the result is
  too long for a key ("Circuit Gilles Villeneuve" → "Villeneuve"), so a
  circuit new to the calendar is labelled correctly without an update.

### Fixed

- The 2026 Bahrain Grand Prix, held at Sepang in Malaysia, showed the Sakhir
  circuit. The circuit map was looked up on OpenF1 by event name as well as
  by circuit, and a Grand Prix keeps its name when it moves venue, so the
  original Bahrain entry won. Maps are now matched on where the race is held:
  the OpenF1 meeting must be in the same country, and either on the same
  weekend or at the same circuit. When nothing qualifies the key shows no map
  rather than the wrong one, so any future relocated or renamed race is
  handled the same way.
- Circuit maps no longer depend on OpenF1 alone. OpenF1 locks every endpoint
  behind an API key while a session is live — exactly when the countdown is
  being watched — and has no map at all for a venue it has never covered,
  such as Sepang. formula1.com's own per-venue maps are now the fallback,
  looked up by circuit rather than by event, and cached with the same
  backoff as the calendar so a missing map costs a few requests an hour.
- Cached circuit maps are now stored under the circuit's id (`sepang`,
  `bahrain`) instead of the town name, so a map cached for one venue can no
  longer be reused for another. Each map is downloaded once more after
  updating.
