## 1.0.2 — 2026-08-22

### Changed

- Rewritten on the PDK 2.x layout under the RDNN id `no.pydeck.utilities`, with Open URL, HTTP Request and Run Script as separate handlers.

### Added

- Open URL can pick which browser to launch, from the browsers actually installed, instead of always going through the system default.
- HTTP Request takes a method and a request body, so it can POST as well as GET.
- Run Script gained a working directory, arguments, a timeout in seconds and an explicit Python executable — so a script can run against a virtualenv rather than whatever `python3` resolves to.
- Run Script polls at 250 ms while a script is running, so the button can show that it is still going rather than looking frozen.

## 1.0.1 — 2026-04-06

### Added

- Sidebar icons for each function, so the three utilities are distinguishable in the action list.

## 1.0.0 — 2026-04-06

### Added

- First release, merging three separate catalog plugins into one entry: Browser (URL launching), Web-Requests (HTTP requests) and Scripts (running bash and Python scripts, published 2026-04-04).

### Changed

- Three marketplace entries became one, since none of them justified a catalog row on its own.

## 0.2.0-beta — 2026-04-03

### Added

- `plugins/plugin/browser/` and `plugins/plugin/web requests/` arrived as separate V2 plugins — URL launching and HTTP requests — alongside the GIF support that let a button animate while a request was in flight.

## 0.1.0-beta — 2026-03-15

### Added

- The ancestors of two of the three utilities shipped in the first pluggable module system: `pydeck/modules/command.py` for running shell commands and `pydeck/modules/http_post.py` for firing HTTP requests.
