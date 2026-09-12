## 2.0.11 — 2026-09-12

### Fixed

- The plugin asked Spotify for playback state around 40 times a minute — about
  57,000 calls a day — which is over the quota a Spotify app is given, and an
  app over its quota is refused for the better part of an hour at a time. Three
  things added up to it. The Play / Pause face fetched every 3 seconds no matter
  what playback said; each of PyDeck's two processes (the server draws the web
  grid, the listener subprocess draws the deck) fetched its own copy of the same
  second; and a refusal was invisible, because `get_playback()` turned every
  error into `None` — indistinguishable from "nothing is playing" — so nothing
  ever backed off and the 429 handler retried straight into the limit, doubling
  the traffic at the worst possible moment. The face is unchanged: its countdown
  was always local, so fetching less often costs nothing on screen.
- Playback is now read every 10 seconds while a track plays, every 15 while it
  is paused and every 30 while nothing is playing, plus one call when the local
  countdown says a track has run out — which is the moment there is something
  new to read. Roughly 6 calls a minute, an eighth of what it was.
- Both processes share one snapshot through the plugin's `state.json`, so the
  second one to ask reads the first one's answer instead of paying for it again.
- A 429 now opens a back-off window for exactly as long as Spotify's
  `Retry-After` asks (capped at an hour), it is published in `state.json` so the
  other process honours it too, and no request is sent while it is open. Being
  rate-limited used to cost 40 calls a minute for as long as it lasted, which is
  what kept the penalty alive; it now costs none.
- Every function's handler shares one copy of `shared.py` per process instead of
  loading its own. A deck with six Spotify buttons had twelve independent
  playback caches, twelve clients and twelve separate rate-limit windows, so a
  refusal one button earned taught the other eleven nothing.
- A volume, shuffle or repeat face on a deck with no Play / Pause button showed
  whatever was true the last time something fetched, forever — it read the
  published snapshot but never refreshed it. Those faces now go through the
  shared cache, which costs nothing when another Spotify face is already keeping
  it current.
- The OAuth redirect URI the plugin builds for its own token exchange used the
  pre-2.0 `spotify` slug, while PyDeck's browser flow has used the plugin id
  since the 2.0 rename. Both now say `.../oauth/no.pydeck.spotify/callback` —
  the URI to register in the Spotify dashboard, unchanged.
