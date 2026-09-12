## 2.0.6 — 2026-08-30

### Fixed

- Every key failed to load on Windows. The optional cairosvg import was guarded
  with `except ImportError`, but on Windows cairosvg imports cleanly and then
  cairocffi raises `OSError` when it cannot dlopen `libcairo-2.dll`, which the
  platform does not ship — so the exception escaped and took the whole module
  down instead of falling through. The guard now catches any exception and drops
  to the bundled Pillow icon set, exactly as it does when the library is simply
  absent.
