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
    value = shared.format_value(
        state, attrs, show_unit=bool(ctx.config.get("show_unit", True))
    )

    # The label row is a <buttonlabel>: the core swaps in the user's button
    # Title when they set one, and falls back to the {name} body otherwise.
    # It can only be hidden by leaving the element out of the template.
    show_label = bool(ctx.config.get("show_label", False))

    if not ctx.config.get("show_value", True):
        value = ""

    ctx.state._template = "display" if show_label else "display-nolabel"
    ctx.state.error = ""
    ctx.state.value = value
    # Long readings (e.g. "5300 MHz") drop a size to stay on one line.
    ctx.state.value_class = shared.value_class(value)
    # Three stacked rows do not fit a 72px button, so the icon gives up room
    # as text rows are added -- and takes it back as they are hidden.
    icon_px = shared.icon_size_for(int(bool(value)) + int(show_label))
    if ctx.config.get("show_icon", True):
        ctx.state.icon_src = shared.icon_src(
            ctx, entity_id, state, attrs,
            highlight=bool(ctx.config.get("highlight_on", True)),
        )
        ctx.state.icon_w = icon_px
        ctx.state.icon_h = icon_px
    else:
        # A 0x0 <img> collapses out of the layout entirely.
        ctx.state.icon_src = ""
        ctx.state.icon_w = 0
        ctx.state.icon_h = 0
    ctx.state.name = shared.friendly_name(entity_id, attrs)
    ctx.refresh()


def _error(ctx: Any, message: str) -> None:
    ctx.state._template = "display-error"
    ctx.state.error = message
    ctx.state.value = ""
    ctx.state.name = ""
    ctx.state.icon_src = ""
    ctx.refresh()
