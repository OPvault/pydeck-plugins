## 1.0.5 — 2026-08-22

### Changed

- Rewritten on the PDK 2.x layout under the RDNN id `no.pydeck.keyboard`, with Press Key and Type Text as separate handlers under `src/functions/`.
- Key presses go through xdotool on X11, which is markedly faster, and fall back to evdev/uinput on Wayland where xdotool cannot reach the compositor.

### Added

- Press-and-hold: a key can be held for as long as the button is down instead of firing once, with a repeat count for the press mode. This first shipped in the classic 1.0.5 on 2026-04-17, and the PDK rewrite kept both the behaviour and the version number.

### Notes

- The uinput fallback needs write access to `/dev/uinput`, so the plugin requires membership of the `input` group: `sudo usermod -aG input $USER`, then log out and back in.

## 1.0.4 — 2026-04-12

### Added

- Sidebar icons for the keyboard actions, and a post-install script that requests the `input` group membership the uinput fallback needs — previously a manual step buried in the description.

## 1.0.2 — 2026-04-06

### Added

- xdotool support, which is markedly faster than uinput on X11 and avoids the device-permission dance entirely when it is available.

## 1.0.1 — 2026-04-05

### Fixed

- Declared the evdev dependency in the manifest, so PyDeck installs it automatically instead of the plugin failing on first press.

## 1.0.0 — 2026-04-04

### Added

- First release: simulate key presses and type text from a button.
