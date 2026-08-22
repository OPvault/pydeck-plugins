## 3.0.0 — 2026-08-22

### Added

- **Analog faces.** A Display option switches the button between digital and analog, with 16 analog styles — classic, minimal, bauhaus, railway, chrono, neon, outline, numerals, blueprint, gold, dots, halo, skeleton, retro, aviator and midnight.
- **16 digital styles** to match: classic, bold, light, mono, lcd, tiles, neon, terminal, card, stacked, headline, ticker, outline, sunrise, minimal and badge.
- **World Clock**, a second function that shows one or two timezones side by side, each with its own location label.
- **Countdown**, a third function that counts down from a duration you type (default `5:00`) and then either holds at zero or counts back up.
- A colour source control on every function: follow the chosen style, follow the button's own colour, or set custom background, foreground and accent colours.
- Optional weekday display, in short or long form, and a date format choice of auto, `MM/DD`, `DD/MM`, dotted, ISO or long.
- A location label you can show under the time, for when a face is standing in for somewhere other than here.
- A custom format field, for when none of the presets are quite right.
- Bundled DOCS.md, shown right after install.

### Changed

- The timezone list grew from 43 entries to 96, ordered west to east rather than grouped by continent, so picking one means scrolling to roughly where you live.
- The 12-hour checkbox became an explicit 24/12 hour-format choice.
- Renamed the original function to **My Clock**, now that it is one of three.
- The poll entry point is named `on_poll`, matching the PDK handler convention.
- The catalog icon moved from `icon.svg` to `icon.png`.
