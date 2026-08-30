## 0.1.0 — 2026-08-30

### Added

- A key that counts pending package updates and tints the number by how
  many there are (green / amber / red at configurable thresholds), with a
  breakdown line such as `12 pac · 3 aur · 1 flat`.
- Supports every common manager and auto-detects which are installed:
  pacman (`checkupdates`, falling back to `pacman -Qu`), AUR helpers (paru,
  yay), APT, DNF, Zypper, XBPS, eopkg, Portage, apk, FreeBSD pkg, Nix,
  Homebrew, Flatpak, Snap, pip (user site), npm (global) and
  `cargo install-update`.
- Checks run on background threads on their own cadence (default every 30
  minutes), so the deck never blocks on a slow mirror.
- Pressing the key re-checks, opens a terminal running each manager's
  upgrade command, or both. Defaults to alacritty; any other terminal can be set, and a
  blank field falls back to `$TERMINAL` and auto-detection.
