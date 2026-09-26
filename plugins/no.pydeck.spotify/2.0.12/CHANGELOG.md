## 2.0.12 — 2026-09-26

- Two plugin-wide settings under Settings → Plugin settings (needs a PyDeck with plugin settings; older versions ignore them and behave as before).
- Check Spotify every (seconds): how often the plugin asks Spotify what is playing, which is how a skip on your phone or a pause in the desktop app reaches the deck. It was fixed at 10 seconds while playing and 15 while paused; it now defaults to 10 for both, can go down to 3, and never checks more often than every 30 seconds while nothing plays, so an idle deck does not spend your app's request quota.
- Keep album art while paused: Play / Pause keeps the song's art, title and frozen time left through a pause instead of dropping to the idle icon, until playback resumes or a different song comes up. The art also survives Spotify dropping the device a few minutes into a pause. Off by default.
