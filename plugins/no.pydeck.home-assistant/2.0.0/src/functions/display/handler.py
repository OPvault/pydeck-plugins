"""HA Display — read-only view of a Home Assistant entity's value."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import shared  # noqa: E402
from ha_client import HaClientError  # noqa: E402


def on_load(ctx: Any) -> None:
    ctx.state._template = "display"
    ctx.state.icon_src = ""
    ctx.state.icon_w = shared.ICON_SIZE
    ctx.state.icon_h = shared.ICON_SIZE
    ctx.state.value = ""
    ctx.state.value_class = "value"
    ctx.state.name = ""
    ctx.state.error = ""


def on_press(ctx: Any) -> None:
    """Read-only — a press just forces an immediate refresh."""
    on_poll(ctx)


def on_poll(ctx: Any, interval: int = 3000) -> None:
    entity_id = shared.entity_id_of(ctx)
    if not entity_id:
        _error(ctx, "Pick an entity")
        return

    try:
        state_obj = shared.fetch_state(ctx, entity_id)
    except HaClientError as exc:
        shared.evict_client(ctx)
        _error(ctx, str(exc))
        return
    except Exception:
        return

    if state_obj is None:
        _error(ctx, "Unavailable")
        return

    state = state_obj.get("state", "")
    attrs = state_obj.get("attributes", {})
    value = shared.format_value(state, attrs)

    # The label row is a <buttonlabel>: the core swaps in the user's button
    # Title when they set one, and falls back to the {name} body otherwise.
    # It can only be hidden by leaving the element out of the template.
    show_label = bool(ctx.config.get("show_label", False))

    ctx.state._template = "display" if show_label else "display-nolabel"
    ctx.state.error = ""
    ctx.state.value = value
    # Long readings (e.g. "1013 hPa") need to drop a size to stay on one line.
    ctx.state.value_class = "value-sm" if len(value) > 6 else "value"
    # Three stacked rows do not fit a 72px button, so the icon gives up the
    # room when the label row is also shown.
    icon_px = shared.ICON_SIZE - 8 if show_label else shared.ICON_SIZE
    ctx.state.icon_w = icon_px
    ctx.state.icon_h = icon_px
    ctx.state.icon_src = (
        shared.icon_src(ctx, entity_id, state, attrs)
        if ctx.config.get("show_icon", True)
        else ""
    )
    ctx.state.name = shared.friendly_name(entity_id, attrs)
    ctx.refresh()


def _error(ctx: Any, message: str) -> None:
    ctx.state._template = "display-error"
    ctx.state.error = message
    ctx.state.value = ""
    ctx.state.name = ""
    ctx.state.icon_src = ""
    ctx.refresh()
