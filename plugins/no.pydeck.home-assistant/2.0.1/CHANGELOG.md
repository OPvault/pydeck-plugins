## 2.0.1 — 2026-08-22

### Added

- Every row of the button face can now be switched off on its own: entity icon, label, on/off state, value and unit. A sensor button can be just a number, and a switch button can be just an icon.
- A Highlight When On option for the toggle button, so an entity that is on is obvious at a glance across the deck.

### Changed

- The icon takes back the room that hidden text rows leave behind instead of staying sized for three rows, so a value-only button gets a much larger icon.
- Long readings pick their own text size, so `5300 MHz` stays on one line instead of overflowing the face.
- The unit toggle only appears once a value is being shown, since a unit with nothing to qualify is meaningless.
