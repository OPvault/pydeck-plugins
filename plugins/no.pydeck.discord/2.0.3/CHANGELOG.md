## 2.0.3 — 2026-08-30

### Added

- Windows support. The RPC layer only ever spoke to a Unix domain socket, so on
  Windows the plugin could not reach Discord at all; it now opens the named pipe
  at `\\.\pipe\discord-ipc-N` there and keeps the socket on Linux and macOS. A
  named pipe has no directory entry to stat — `os.path.exists()` on one opens an
  instance rather than answering a question — so the ten candidates are handed
  back unfiltered and the live one is found by trying to open each.
- macOS socket discovery now also searches `$TMPDIR`. That is where the per-user
  temp dir keeps `discord-ipc-N`, and only `/tmp` was being checked.

### Changed

- Both transports sit behind one `_Conn` object, so a handler issues
  `conn.request(...)` and never has to know which one it is talking to. They are
  genuinely not interchangeable underneath: a Unix socket can be drained by a
  background reader thread while another thread writes, but a named pipe opened
  by `open()` is a synchronous handle whose I/O the kernel serialises, so a
  reader parked in `read()` would block the next write outright for as long as
  Discord stayed quiet. On Windows the caller therefore drives its own round trip
  under a lock, with `PeekNamedPipe` supplying the timeout a blocking read cannot.
- Opening a connection gets its own 60-second budget. Discord answers an ordinary
  command in milliseconds but can sit on the handshake and AUTHENTICATE far longer
  on a cold client, and the per-command timeout was cutting those off.
- `shared.py` asks the client `is_connected()` instead of reading its private
  `_sock` attribute to decide whether a press can go straight out.

### Fixed

- A connection dropped by Discord now triggers a reconnect rather than escaping as
  an unhandled `OSError` — the voice-state calls catch it alongside
  `DiscordRPCError`.
