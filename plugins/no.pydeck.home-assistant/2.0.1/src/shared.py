"""Home Assistant PDK plugin — shared utilities.

Credential loading, a cached :class:`HaClient` per instance, entity state
helpers, and the editor-facing ``api_domains`` / ``api_entities`` endpoints
behind the two chained ``api_select`` fields.

Per-function handlers live under ``src/functions/<name>/handler.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_SRC_DIR = Path(__file__).parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from ha_client import (  # noqa: E402
    HaClient,
    HaClientError,
    default_icon,
    render_entity_icon,
)

_CREDS_PATH = Path.home() / ".config" / "pydeck" / "core" / "credentials.json"

# The core writes credentials under the RDNN id but reads every alias, so a
# plugin reading the file itself must try both -- RDNN last so a migrated
# blob wins.  "ha" is an older hand-written key kept as a final fallback.
PLUGIN_ID = "no.pydeck.home-assistant"
_LEGACY_PLUGIN_IDS = ("ha", "home-assistant")

ICON_ON_COLOR = "#ffd54a"
ICON_OFF_COLOR = "#c8d2e0"

# Icons are rasterized larger than they are drawn so they stay crisp when the
# renderer targets a canvas bigger than the 72px base (XL decks, hi-res web
# previews); the layout size is in canvas units.
ICON_RASTER = 96
ICON_SIZE = 24

_ON_STATES = {"on", "open", "unlocked", "playing", "home", "active"}
_DEAD_STATES = {"unavailable", "unknown", ""}

# Cached clients keyed by (url, token).
_client_cache: Dict[Tuple[str, str], HaClient] = {}

# Last known state/attributes per (url, entity_id).
#
# These must be keyed by entity rather than read back off ctx.state: the PDK
# runtime keeps ONE state dict per *function*, shared by every button using
# that function, so ctx.state on press may still hold whichever button was
# polled last.  The optimistic toggle needs this button's own last state.
_state_cache: Dict[Tuple[str, str], str] = {}
_attrs_cache: Dict[Tuple[str, str], dict] = {}


# ── Credentials ────────────────────────────────────────────────────────────────


def load_credentials(ctx: Any = None) -> Dict[str, Any]:
    """Return the plugin's credentials.

    ``ctx.credentials`` is populated on press and on the server's poll, but
    the hardware listener dispatches poll without them -- so read
    credentials.json directly and treat ctx as an overlay when present.
    """
    merged: Dict[str, Any] = {}
    try:
        if _CREDS_PATH.is_file():
            raw = json.loads(_CREDS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in (*_LEGACY_PLUGIN_IDS, PLUGIN_ID):
                    entry = raw.get(key)
                    if isinstance(entry, dict):
                        merged.update({k: v for k, v in entry.items() if v})
    except Exception:
        pass
    if ctx is not None:
        ctx_creds = getattr(ctx, "credentials", None)
        if isinstance(ctx_creds, dict):
            merged.update({k: v for k, v in ctx_creds.items() if v})
        # A button may override the instance per-button via its config.
        ctx_config = getattr(ctx, "config", None)
        if isinstance(ctx_config, dict):
            for key in ("url", "token"):
                if ctx_config.get(key):
                    merged[key] = ctx_config[key]
    return merged


def get_client(ctx: Any = None) -> HaClient:
    """Return a cached :class:`HaClient`.

    Raises:
        HaClientError: when the URL or token has not been configured.
    """
    creds = load_credentials(ctx)
    url = str(creds.get("url") or "").strip()
    token = str(creds.get("token") or "").strip()
    if not url or not token:
        raise HaClientError(
            "Home Assistant URL and token are required — "
            "configure them under Settings → Credentials"
        )
    key = (url, token)
    client = _client_cache.get(key)
    if client is None:
        client = HaClient(url, token)
        _client_cache[key] = client
    return client


def evict_client(ctx: Any = None) -> None:
    """Drop cached clients so the next call reconnects."""
    _client_cache.clear()


# ── Entity helpers ─────────────────────────────────────────────────────────────


def entity_id_of(ctx: Any) -> str:
    return str(ctx.config.get("entity_id") or "").strip()


def _attrs_key(ctx: Any, entity_id: str) -> Tuple[str, str]:
    creds = load_credentials(ctx)
    return (str(creds.get("url") or "").strip(), entity_id)


def is_on(state: str) -> bool:
    return (state or "").strip().lower() in _ON_STATES


def is_available(state: str) -> bool:
    """False for entities HA reports as unavailable/unknown.

    Those must not render as a confident "OFF" -- the device may well be on
    and simply unreachable.
    """
    return (state or "").strip().lower() not in _DEAD_STATES


def resolve_icon(entity_id: str, state: str, attrs: dict) -> str:
    """Pick the best MDI icon name for an entity."""
    icon = attrs.get("icon", "")
    if icon:
        return icon
    return default_icon(entity_id, state, attrs.get("device_class", ""))


def icon_src(
    ctx: Any, entity_id: str, state: str, attrs: dict, highlight: bool = True
) -> str:
    """Rasterize the entity's icon and return a storage-relative src.

    With *highlight* off the icon keeps its neutral tint regardless of state,
    for users who would rather not have an accent colour on the deck.
    """
    name = resolve_icon(entity_id, state, attrs)
    color = ICON_ON_COLOR if (highlight and is_on(state)) else ICON_OFF_COLOR
    return render_entity_icon(
        name, ctx.storage_path, size=ICON_RASTER, color=color
    )


def friendly_name(entity_id: str, attrs: dict) -> str:
    name = str(attrs.get("friendly_name") or "").strip()
    if name:
        return name
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


def format_value(state: str, attrs: dict, show_unit: bool = True) -> str:
    """Render a sensor value, optionally with its unit."""
    text = str(state or "").strip()
    if not text:
        return ""
    if not text.isalpha():
        unit = str(attrs.get("unit_of_measurement") or "").strip()
        if show_unit and unit:
            sep = "" if unit.startswith("°") else " "
            return f"{text}{sep}{unit}"
        return text
    return text.replace("_", " ").title()


def icon_size_for(text_rows: int) -> int:
    """Icon size in canvas units for a face with *text_rows* text lines.

    Hiding rows should give the icon the space back rather than leaving a
    gap, so an icon-only button draws it large.
    """
    if text_rows <= 0:
        return ICON_SIZE + 16
    if text_rows == 1:
        return ICON_SIZE
    return ICON_SIZE - 6


def value_class(text: str) -> str:
    """Pick the largest value style that still fits one line on a 72px face.

    <text> is single-line and does not wrap or auto-shrink, so the size has
    to be chosen up front from the string length.
    """
    n = len(text or "")
    if n <= 4:
        return "value"
    if n <= 6:
        return "value-md"
    if n <= 7:
        return "value-sm"
    return "value-xs"


def remember(ctx: Any, entity_id: str, state: str, attrs: dict) -> None:
    key = _attrs_key(ctx, entity_id)
    _state_cache[key] = state or ""
    _attrs_cache[key] = attrs or {}


def recall_state(ctx: Any, entity_id: str) -> str:
    return _state_cache.get(_attrs_key(ctx, entity_id), "")


def recall_attrs(ctx: Any, entity_id: str) -> dict:
    return _attrs_cache.get(_attrs_key(ctx, entity_id), {})


def fetch_state(ctx: Any, entity_id: str) -> Optional[dict]:
    """Fetch one entity's state object, or None when unavailable."""
    client = get_client(ctx)
    state_obj = client.get_state(entity_id)
    if not isinstance(state_obj, dict):
        return None
    remember(ctx, entity_id, state_obj.get("state", ""),
             state_obj.get("attributes", {}))
    return state_obj


# ── API endpoint functions (for api_select UI fields) ──────────────────────────


def api_domains(config: Dict[str, Any]) -> list:
    """Unique entity domains, with an 'All' option to clear the filter."""
    client = _client_from_config(config)
    seen: Dict[str, str] = {}
    for s in client.list_states():
        domain = s["entity_id"].split(".")[0]
        seen.setdefault(domain, domain.replace("_", " ").title())
    return [{"label": "All", "value": ""}] + [
        {"label": label, "value": domain} for domain, label in sorted(seen.items())
    ]


def api_entities(config: Dict[str, Any]) -> list:
    """Entities for the picker, optionally scoped by ``domain``."""
    client = _client_from_config(config)
    domain_filter = str(config.get("domain") or "").strip()
    return [
        {
            "entity_id": s["entity_id"],
            "name": friendly_name(s["entity_id"], s.get("attributes", {})),
            "state": s.get("state", ""),
            "domain": s["entity_id"].split(".")[0],
        }
        for s in client.list_states()
        if not domain_filter or s["entity_id"].split(".")[0] == domain_filter
    ]


def _client_from_config(config: Dict[str, Any]) -> HaClient:
    """Build a client for the API endpoints, which get a plain config dict.

    The core merges stored credentials into that dict, but fall back to
    reading them from disk so the editor still works if it did not.
    """
    url = str(config.get("url") or "").strip()
    token = str(config.get("token") or "").strip()
    if not url or not token:
        creds = load_credentials()
        url = url or str(creds.get("url") or "").strip()
        token = token or str(creds.get("token") or "").strip()
    if not url or not token:
        raise HaClientError(
            "Home Assistant URL and token are required — "
            "configure them under Settings → Credentials"
        )
    key = (url, token)
    client = _client_cache.get(key)
    if client is None:
        client = HaClient(url, token)
        _client_cache[key] = client
    return client
