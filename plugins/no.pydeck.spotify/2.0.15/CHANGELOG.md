## 2.0.15 — 2026-10-10

- Play / Pause starts the music again after a long pause. A few minutes after playback stops, Spotify stops treating any device as active, and a play with nowhere to go was refused -- the press did nothing. It now finds a running Spotify app through the device list and resumes there: the one picked under the new *Start playback on* plugin setting, else the device that played last. Music already playing or paused on a device stays there.
- A press with nowhere to play now says so ("No Spotify app is running", or that the picked device is not available) instead of silently doing nothing.
