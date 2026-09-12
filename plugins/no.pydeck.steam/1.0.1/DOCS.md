# Steam

Put your Steam games on the deck. Each **Launch Game** key is one game, and
its face is the game's icon (the one Steam shows in its sidebar) or, if you
prefer, its library poster.

## Setup

1. Drag **Launch Game** onto a key.
2. Pick the game in the **Game** dropdown — it lists every installed game
   across all of your Steam library folders, most recently played first.
3. **Key face** picks the game icon (default), the logo Steam draws over the
   library banner, or the library poster; the poster can fill the key or be
   shown whole. Artwork Steam hasn't cached falls back to the icon. Tick **Show game title** to
   print the name underneath / over it.

Press the key to start the game. If Steam isn't running it's started first.

## Where the data comes from

- **Game list** — `appmanifest_*.acf` in every `steamapps` folder listed in
  Steam's `libraryfolders.vdf`. Proton, Steam Linux Runtime and the
  Steamworks redistributables are hidden; games mid-download are skipped
  until they finish. A library folder on a drive that isn't currently
  attached is simply passed over.
- **Icons and posters** — Steam's `appcache/librarycache/<appid>/` (the
  hash-named square icon, `logo.png`, and the 600×900 portrait). Open the game's page in the Steam client once if a game shows a
  plain name instead of its poster; that makes Steam cache the image.
- **Steamworks SDK** — the runtime is loaded for `SteamAPI_IsSteamRunning`:
  `libsteam_api.so`, which the Linux client ships, or `steam_api64.dll` on
  Windows. The Windows client ships only `steamclient64.dll`, so unless you
  set `STEAMWORKS_SDK` to a downloaded SDK the plugin falls back to the same
  `HKCU\Software\Valve\Steam\ActiveProcess` pid the SDK reads. Either way
  the SDK has no call that lists a user's library, so the manifest files
  above remain the source of truth.

## Steam locations checked

**Linux** — `~/.local/share/Steam`, `~/.steam/steam`, `~/.steam/root`, or the
Flatpak `com.valvesoftware.Steam` data dirs. Games are started with the
`steam` binary, falling back to `xdg-open` or `flatpak run`.

**Windows** — `SteamPath` under `HKCU\Software\Valve\Steam` and
`InstallPath` under `HKLM\SOFTWARE\WOW6432Node\Valve\Steam`, so a Steam
moved off the system drive is still found, then
`%ProgramFiles(x86)%\Steam` and `%ProgramFiles%\Steam`. Games are started
with `steam.exe`, falling back to handing the `steam://` URL to Explorer.

On either platform `STEAM_ROOT` overrides all of it.

## Trademark

©2026 Valve Corporation. Steam® and the Steam logo are trademarks and/or
registered trademarks of Valve Corporation in the U.S. and/or other countries.
This plugin is not sponsored, endorsed, licensed by, or affiliated with Valve.
