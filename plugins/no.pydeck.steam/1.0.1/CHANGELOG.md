## 1.0.1 — 2026-08-30

### Added

- Windows support. Steam's data directory is located through the registry
  (`SteamPath` under HKCU, `InstallPath` under HKLM) before the standard
  Program Files locations, so an install moved to another drive is still
  found, and games start through `steam.exe` — falling back to handing the
  `steam://` URL to Explorer. Library folders, the artwork cache and the
  manifest format are byte-identical to Linux, so the game list and every
  key face work unchanged.
- The Steamworks runtime is loaded as `steam_api64.dll` on Windows. The
  client there ships only `steamclient64.dll`, so with no downloaded SDK
  present the running-state check reads the same `ActiveProcess` pid that
  `SteamAPI_IsSteamRunning` itself consults, instead of reporting "unknown".

### Fixed

- An empty `STEAM_ROOT` resolved to the process working directory and was
  then searched as though it were a Steam install.
