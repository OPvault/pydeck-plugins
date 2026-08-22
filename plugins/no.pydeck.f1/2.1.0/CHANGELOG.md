## 2.1.0 — 2026-08-22

### Fixed

- The countdown no longer claims the season is over when it simply could not reach the calendar. A failed fetch now reads **No Data**, and **Off Season** is kept for the case where a calendar really was read and had nothing left in it.

### Changed

- The race calendar is cached under the button's own storage path rather than a module-level global, so the server and the hardware listener stop fighting over one another's copy.
