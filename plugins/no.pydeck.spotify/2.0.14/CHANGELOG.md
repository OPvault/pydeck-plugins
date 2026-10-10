## 2.0.14 — 2026-10-09

- Picks up a new Spotify authorization without a restart. The plugin kept its signed-in client in memory and only read the stored tokens when it had none, so after Spotify revoked a token and you authorized again, every button went on using the dead one until PyDeck was restarted. It now notices that the stored tokens changed and switches to them on the next poll or press.
