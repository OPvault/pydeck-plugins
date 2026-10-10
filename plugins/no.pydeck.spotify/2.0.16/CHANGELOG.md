## 2.0.16 — 2026-10-10

- A Spotify server setting under Settings → Plugin settings. Empty keeps talking to Spotify itself; an address points sign-in, token refresh and playback at a stand-in such as SpotiProxy, so PyDeck can share one Spotify app and its request quota with other apps on the same network. Authorize again after changing it.
- When Spotify asks PyDeck to wait, all of the wait is honoured, in both of PyDeck's processes and for token refreshes too: before, the shared window ended after an hour however long Spotify had asked for, and a refresh went out regardless. Through a Spotify server the server keeps the wait instead, and PyDeck asks it freely.
- A new sign-in picked up from the store also brings its expiry time, so the client refreshes it when it actually runs out rather than on its first use.
