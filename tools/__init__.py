"""Development tools for the pydeck-plugins repo."""

import os
import sys

# Compiled bytecode goes to the one cache root (~/.cache/pydeck/pycache), not
# into __pycache__ folders next to the sources — the same rule as the PyDeck
# checkout. This package is imported before any tools.* module, so
# `python -m tools.pdk_create` never litters the checkout. An explicit
# PYTHONPYCACHEPREFIX (e.g. from the parent process) wins.
_pycache_prefix = (os.environ.get("PYTHONPYCACHEPREFIX") or "").strip()
if not _pycache_prefix:
    _xdg_cache = (os.environ.get("XDG_CACHE_HOME") or "").strip() or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    _pycache_prefix = os.path.join(_xdg_cache, "pydeck", "pycache")
    os.environ["PYTHONPYCACHEPREFIX"] = _pycache_prefix
sys.pycache_prefix = _pycache_prefix
