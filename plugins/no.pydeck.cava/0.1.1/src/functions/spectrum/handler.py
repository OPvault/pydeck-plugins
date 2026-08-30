"""Spectrum -- live audio bars from cava."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

# PDK function modules are imported through an explicit spec, so the plugin's
# source directory never lands on sys.path -- load the shared module by path.
_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("pdk_cava_shared", str(_ROOT / "shared.py"))
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

# The poll only carries settings changes; the bars themselves are read at
# render time (see shared.py) because the deck listener never polls faster
# than once a second.
POLL_MS = 1000


def render(ctx: Any) -> None:
    ctx.state.clear()
    ctx.state._template = "spectrum"
    ctx.state.update(_shared.live_state(ctx.config))


def on_load(ctx: Any) -> None:
    ctx.state._template = "spectrum"
    ctx.state.update(_shared.face_state({}, [0] * 12, None))


def on_poll(ctx: Any, interval: int = POLL_MS) -> None:
    render(ctx)


def on_press(ctx: Any) -> None:
    render(ctx)
