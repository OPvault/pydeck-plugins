"""My Clock -- an analog or digital clock for your default location."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

# PDK function modules are imported through an explicit spec, so the plugin's
# source directory never lands on sys.path -- load the shared module by path.
_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("pdk_clock_shared", str(_ROOT / "shared.py"))
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)


def _caption(cfg: dict) -> str:
    """The place name under the time, empty when the user turned it off."""
    custom = str(cfg.get("location_label") or "").strip()
    if custom:
        return custom
    if not cfg.get("show_location", False):
        return ""
    return _shared.zone_label(str(cfg.get("timezone", "local")))


def render(ctx: Any) -> None:
    """Recompute the whole face.  Called on load, on poll and on press."""
    cfg = ctx.config
    now = _shared.now_in(str(cfg.get("timezone", "local")), cfg)

    if str(cfg.get("display_mode", "digital")) == "analog":
        state = _shared.analog_state(now, cfg, caption=_caption(cfg))
    else:
        state = _shared.digital_state(now, cfg, caption=_caption(cfg))

    ctx.state.clear()
    ctx.state.update(state)


def on_load(ctx: Any) -> None:
    render(ctx)


def on_poll(ctx: Any, interval: int = 1000) -> None:
    render(ctx)


def on_press(ctx: Any) -> None:
    render(ctx)
