"""HA Toggle — flip a Home Assistant entity on/off and mirror its state."""

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
    ctx.state._template = "toggle"
    ctx.state.icon_src = ""
    ctx.state.icon_w = shared.ICON_SIZE
    ctx.state.icon_h = shared.ICON_SIZE
    ctx.state.name = ""
    ctx.state.state_text = ""
    ctx.state.state_class = "state-off"
    ctx.state.error = ""


def on_press(ctx: Any) -> None:
    """Toggle the entity, then show the assumed state immediately.

    The poll loop reconciles with the real state a few seconds later, so a
    service call that silently fails self-corrects rather than sticking.
    """
    entity_id = shared.entity_id_of(ctx)
    if not entity_id:
        _error(ctx, "Pick an entity")
        return

    try:
        client = shared.get_client(ctx)
        client.toggle(entity_id)
    except HaClientError as exc:
        shared.evict_client(ctx)
        _error(ctx, str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - surface anything on the button
        shared.evict_client(ctx)
        _error(ctx, f"Error: {exc}")
        return

    # Read the previous state from the per-entity cache, not ctx.state --
    # that dict is shared with every other button using this function.
    assumed = "off" if shared.is_on(shared.recall_state(ctx, entity_id)) else "on"
    shared.remember(ctx, entity_id, assumed, shared.recall_attrs(ctx, entity_id))
    _render(ctx, entity_id, assumed, shared.recall_attrs(ctx, entity_id))


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
        # Transient network trouble — keep the last good face rather than
        # flashing an error on every poll tick.
        return

    if state_obj is None:
        _error(ctx, "Unavailable")
        return

    _render(
        ctx,
        entity_id,
        state_obj.get("state", ""),
        state_obj.get("attributes", {}),
    )


def _render(ctx: Any, entity_id: str, state: str, attrs: dict) -> None:
    on = shared.is_on(state)
    available = shared.is_available(state)
    # The label row is a <buttonlabel>: the core swaps in the user's button
    # Title when they set one, and falls back to the {name} body otherwise.
    # It can only be hidden by leaving the element out of the template.
    show_label = bool(ctx.config.get("show_label", True))
    ctx.state._template = "toggle" if show_label else "toggle-nolabel"
    ctx.state.error = ""
    ctx.state.icon_src = shared.icon_src(ctx, entity_id, state, attrs)
    ctx.state.icon_w = shared.ICON_SIZE
    ctx.state.icon_h = shared.ICON_SIZE
    if not available:
        ctx.state.state_text = "N/A"
        ctx.state.state_class = "state-off"
    else:
        ctx.state.state_text = "ON" if on else "OFF"
        ctx.state.state_class = "state-on" if on else "state-off"
    ctx.state.name = shared.friendly_name(entity_id, attrs)
    ctx.refresh()


def _error(ctx: Any, message: str) -> None:
    ctx.state._template = "toggle-error"
    ctx.state.error = message
    # Clear the value fields so a stale reading from another button can never
    # be shown next to an error.
    ctx.state.state_text = ""
    ctx.state.name = ""
    ctx.state.icon_src = ""
    ctx.refresh()
