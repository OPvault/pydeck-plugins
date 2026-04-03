"""Home Assistant plugin for PyDeck.

Controls and monitors Home Assistant entities via the REST API.

Setup:
1. In Home Assistant, go to your profile and create a Long-Lived Access Token
2. Enter your HA URL and token under Settings → API
3. Drag "HA Toggle" or "HA Display" onto a button and pick an entity
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

_PLUGIN_DIR = Path(__file__).parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from ha_client import HaClient, HaClientError, default_icon, render_entity_icon  # noqa: E402

# Module-level client cache keyed by (url, token).
_client_cache: dict[tuple[str, str], HaClient] = {}

# Per-entity state cache for change detection in poll functions.
# Keyed by (url, entity_id) to avoid collisions across different HA instances.
_state_cache: dict[tuple[str, str], str] = {}

# Per-entity attributes cache so optimistic toggle display preserves custom icons.
# Keyed by (url, entity_id).
_attrs_cache: dict[tuple[str, str], dict] = {}


def _get_client(config: Dict[str, Any]) -> HaClient:
    """Return a cached HaClient, creating one if needed.

    Raises:
        ValueError: If credentials are missing.
    """
    url = str(config.get("url") or "").strip()
    token = str(config.get("token") or "").strip()
    if not url or not token:
        raise ValueError(
            "Home Assistant URL and token are required — "
            "configure them under Settings → API"
        )
    key = (url, token)
    client = _client_cache.get(key)
    if client is None:
        client = HaClient(url, token)
        _client_cache[key] = client
    return client


def _evict_client(config: Dict[str, Any]) -> None:
    """Remove a stale client so the next press creates a fresh connection."""
    key = (
        str(config.get("url") or "").strip(),
        str(config.get("token") or "").strip(),
    )
    _client_cache.pop(key, None)


def _entity_key(config: Dict[str, Any]) -> tuple[str, str]:
    """Return a stable cache key scoped to both the HA instance and entity."""
    return (
        str(config.get("url") or "").strip(),
        str(config.get("entity_id") or "").strip(),
    )


def _resolve_icon(entity_id: str, state: str, attrs: dict) -> str:
    """Pick the best MDI icon name for an entity."""
    icon = attrs.get("icon", "")
    if icon:
        return icon
    return default_icon(entity_id, state, attrs.get("device_class", ""))


def _build_display(
    entity_id: str,
    state_obj: dict,
    include_text: bool = False,
) -> Dict[str, Any]:
    """Build a display_update dict from an entity state object.

    When *include_text* is True (sensor/display buttons) the sensor value
    is written to ``text`` so it appears as the button label.  Toggle
    buttons leave text alone so the user's custom name is preserved.

    Falls back to a plain color/text display if icon rendering fails.
    """
    state = state_obj.get("state", "")
    attrs = state_obj.get("attributes", {})
    icon_name = _resolve_icon(entity_id, state, attrs)
    icon_path = render_entity_icon(icon_name, is_on=(state == "on"))

    result: Dict[str, Any] = {}
    if icon_path:
        result["image"] = icon_path
    else:
        result["color"] = "#1a3a6e"

    if include_text:
        unit = attrs.get("unit_of_measurement", "")
        result["text"] = f"{state} {unit}".strip() if unit else state

    return result


# ── Private poll helper ───────────────────────────────────────────────────────


def _poll_entity(config: Dict[str, Any], include_text: bool) -> Dict[str, Any]:
    """Shared implementation for poll_toggle and poll_display.

    Fetches the entity state, compares it to the cached value, and returns
    a ``display_update`` dict only when the state has actually changed.
    Returns ``{}`` when nothing changed or on any error.
    """
    entity_id = str(config.get("entity_id") or "").strip()
    if not entity_id:
        return {}

    try:
        client = _get_client(config)
        state_obj = client.get_state(entity_id)
        new_state = state_obj.get("state", "")
        new_attrs = state_obj.get("attributes", {})

        key = _entity_key(config)
        prev_state = _state_cache.get(key)

        if new_state == prev_state:
            return {}

        _state_cache[key] = new_state
        _attrs_cache[key] = new_attrs

        display = _build_display(entity_id, state_obj, include_text=include_text)
        return {"display_update": display}
    except Exception:
        return {}


# ── Plugin functions ──────────────────────────────────────────────────────────


def toggle(config: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle a Home Assistant entity on/off.

    Fires the toggle service call and immediately returns an assumed
    opposite state so the deck updates instantly.  The poll loop will
    sync with the real state within a few seconds.
    """
    entity_id = str(config.get("entity_id") or "").strip()
    if not entity_id:
        return {"success": False, "error": "No entity selected"}

    try:
        client = _get_client(config)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        client.toggle(entity_id)

        key = _entity_key(config)
        prev = _state_cache.get(key, "off")
        assumed = "off" if prev == "on" else "on"
        _state_cache[key] = assumed

        cached_attrs = _attrs_cache.get(key, {})
        assumed_state_obj = {"state": assumed, "attributes": cached_attrs}
        display = _build_display(entity_id, assumed_state_obj)

        return {"success": True, "state_value": assumed, "display_update": display}
    except HaClientError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_client(config)
        return {"success": False, "error": f"Unexpected error: {e}"}


def display(config: Dict[str, Any]) -> Dict[str, Any]:
    """Read-only sensor display — fetch current value on press."""
    entity_id = str(config.get("entity_id") or "").strip()
    if not entity_id:
        return {"success": True}

    try:
        client = _get_client(config)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        state_obj = client.get_state(entity_id)
        key = _entity_key(config)
        _state_cache[key] = state_obj.get("state", "")
        _attrs_cache[key] = state_obj.get("attributes", {})
        disp = _build_display(entity_id, state_obj, include_text=True)
        return {"success": True, "display_update": disp}
    except HaClientError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
    except Exception as e:
        _evict_client(config)
        return {"success": False, "error": f"Unexpected error: {e}"}


def poll_toggle(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll: update toggle button icon when state changes."""
    return _poll_entity(config, include_text=False)


def poll_display(config: Dict[str, Any]) -> Dict[str, Any]:
    """Background poll: update display button icon + sensor value."""
    return _poll_entity(config, include_text=True)


# ── Plugin API endpoints (called via /api/plugins/ha/api/<name>) ─────────────


def api_entities(config: Dict[str, Any]) -> list:
    """Return all HA entities for the entity picker.

    Raises on missing credentials or connection failure so the generic
    API route can return a proper error message to the UI.
    """
    client = _get_client(config)
    states = client.list_states()
    return [
        {
            "entity_id": s["entity_id"],
            "name": s.get("attributes", {}).get(
                "friendly_name", s["entity_id"]
            ),
            "state": s.get("state", ""),
            "domain": s["entity_id"].split(".")[0],
        }
        for s in states
    ]
