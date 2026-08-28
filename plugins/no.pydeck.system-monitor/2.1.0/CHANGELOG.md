## 2.1.0 — 2026-08-28

### Fixed

- The GPU readout had its two numbers the wrong way round: the big value was
  the temperature and the small one underneath was utilisation, while CPU, RAM
  and Disk all put the percentage on the face and the detail beneath it. A row
  of monitor keys was unreadable at a glance because one of them meant
  something different. GPU now leads with utilisation, like the rest, and the
  bar tracks utilisation rather than switching to temperature whenever the
  usage line was turned off.

### Added

- Network and Battery readouts. Network shows live download and upload rates
  per interface (or every real one summed) with a bar scaled to a link speed
  you set; Battery shows charge, draw and estimated time left.
- 18 themes — Classic, Carbon, Slate, Light, Paper, Mono, Terminal, LCD, Amber,
  Neon, Midnight, Ocean, Sunset, Blueprint, Nord, Dracula, Gruvbox, Solarized —
  each with its own threshold ramp, so a warning still reads as a warning in a
  palette that has no GitHub amber in it.
- 5 layouts: Stat, Minimal, Gauge, Split and Graph. Graph plots the last 14
  readings, kept per button, so two Disk keys on different mount points draw
  their own line.
- The main value and the sub line are now chosen independently on every
  readout. CPU gained clock speed, load average, core count and uptime; RAM
  gained swap and free space; GPU gained VRAM and board power; Disk gained free
  space and the mount point.
- Warn and critical gates are editable per button instead of being fixed at
  60/85, with a separate pair in °C for tinting by temperature.
- **Palette** takes the face's colours from the theme, from the button's own
  colour or gradient, or from three hex fields of your own. Ink that would land
  too close to the chosen background is swapped for one that still reads.
- Header text, sub line and bar can each be turned off, the header relabelled,
  and percentages shown to one decimal place.
- A bundled DOCS.md.

### Changed

- A press on any monitor key now forces an immediate re-read instead of doing
  nothing until the next poll.
