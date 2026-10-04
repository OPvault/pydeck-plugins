## 2.1.2 — 2026-10-04

- Now requires PyDeck 2.0.0, which has the shared settings this version follows (Settings → Plugin settings → Shared by all plugins).
- CPU and GPU temperature can be shown in Kelvin, and the unit has a new default, **Use global**, which follows the shared temperature setting. A key set to C or F keeps it.
- The shared status colors tint every reading — but only once you change them: left at PyDeck's defaults, each of the 18 themes keeps the palette drawn for it. A color too close to a theme's background is shaded so it still reads, and a key's own Custom colors still win.
- Decimals follow the shared separator (`12,5%`, `3,2/16G`). Interface names, mounts and GPU names in the sub line are left alone.
- Spelling is American English throughout (color, utilization).
