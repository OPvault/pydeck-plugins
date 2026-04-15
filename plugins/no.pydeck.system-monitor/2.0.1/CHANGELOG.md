## 2.0.1 — 2026-04-15

### Changed

- Restructured onto the current PDK layout — `src/functions/<name>/` — replacing the per-function `<fn>/<fn>.xml` pairs and flat `plugin.py`.
- Re-homed under the RDNN id `no.pydeck.system-monitor`.

## 2.0.0 — 2026-04-12

### Changed

- First PDK release: per-function XML templates replaced the flat `plugin.py` renderer, and each monitor's readout controls moved into a collapsible display group.
- Backend lists were pruned to the ones that actually worked headlessly — `htop` dropped from the CPU and RAM backends, `nvtop` from the GPU backends, and `sysfs` added for GPUs with no vendor tool installed.

## 1.0.0 — 2026-04-03

### Added

- First release: live CPU, RAM, GPU and disk buttons.
- Readings come from `/proc/stat`, `/proc/meminfo`, `sensors`, `df`, `nvidia-smi`, `rocm-smi` and `/sys/class/drm`, with the backend selectable per button so a machine missing one tool can fall back to another.
- No extra Python packages required — everything is read from files and standard command-line tools.
