## 2.0.14 — 2026-10-09

- A Spotify server setting under Settings → Plugin settings. Empty keeps talking to Spotify itself; an address points sign-in, token refresh and playback at a stand-in such as SpotiProxy, so PyDeck can share one Spotify app and its request quota with other apps on the same network. Authorize again after changing it.
- When Spotify asks PyDeck to wait, all of the wait is honoured, in both of PyDeck's processes and for token refreshes too: before, the shared window ended after an hour however long Spotify had asked for, and a refresh went out regardless. Through a Spotify server the server keeps the wait instead, and PyDeck asks it freely.
- After Authorize, the buttons use the new sign-in at once: before, a process that had already started kept the old tokens until PyDeck restarted.

## 2.0.13 — 2026-10-04

- Now requires PyDeck 2.0.0. The two plugin-wide settings added in 2.0.12 live on Settings → Plugin settings, which an older PyDeck does not have, so its users were stuck on the defaults with no way to change them; the marketplace now offers this version only to a PyDeck that can show them.
