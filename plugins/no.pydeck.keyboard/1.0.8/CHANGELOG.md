## 1.0.8 — 2026-08-30

### Changed

- xdotool is declared as an optional `system_packages` dependency: on an X11 session PyDeck
  offers to install it through the system package manager, with the exact command shown for
  approval. Skipping it — and every Wayland session — keeps using the evdev/uinput path.

## 1.0.7 — 2026-08-30

- Redrew the Press Key and Type Text sidebar icons (keycap and text cursor) and the marketplace logo (keyboard outline).
