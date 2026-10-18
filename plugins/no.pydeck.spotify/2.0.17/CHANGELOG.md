## 2.0.17 — 2026-10-18

### Fixed

- Keep album art while paused now works on the deck and in the web UI alike. The art was held only by a PyDeck process that had watched the track play, so one that started or restarted during a pause -- often the deck's -- showed the Play/Pause icon while the other showed the art. The paused face is now read off Spotify's playback alone, and a pause long enough that Spotify stops naming the track falls back to the last track either process saw.
- The web UI could show a plain gray key instead of the album art. Both PyDeck processes rewrote the art file in place, and a render that caught it half-written drew no image; the art and the playback state are now written to a temporary file and swapped in.
