## 2.0.4 — 2026-09-12

### Fixed

- A Flatpak Discord could not be reached on Flatpak 1.16 or newer: nothing the
  plugin did would connect, and every function failed with "Discord IPC socket
  not found — is Discord running?" while Discord was plainly running. Flatpak
  moved the per-app runtime directory from `$XDG_RUNTIME_DIR/app/<app-id>/` to
  `$XDG_RUNTIME_DIR/.flatpak/<app-id>/xdg-run/`, and it still creates the old
  path — empty — so the socket search found a directory and no socket in it. Both
  layouts are now searched, for Discord, PTB and Canary, so the plugin works on
  either Flatpak version. No re-authorization is needed.
