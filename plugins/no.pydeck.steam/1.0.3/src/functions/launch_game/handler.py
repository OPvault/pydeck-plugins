"""PDK handler for `launch_game` — one key, one Steam game, its icon or poster as the face."""

from __future__ import annotations

import sys
import time
from typing import Any

from lib.plugins.ids import python_import_module_name

_ICON = "assets/icons/steam.svg"
_FLASH_S = 2.0

# The state dict is shared by every button on this function, so anything
# per-button is derived from ctx.config on each poll rather than stored.
_launched_at: dict[int, float] = {}


def _shared() -> Any:
    return sys.modules[python_import_module_name("pdk_plugin_", "no.pydeck.steam")]


def _truthy(value: Any) -> bool:
    return value is True or str(value).lower() in ("true", "on", "1", "yes")


def _idle(ctx: Any, label: str) -> None:
    ctx.state._template = "launch_game_idle"
    ctx.state.icon_src = _ICON
    ctx.state.label = label
    ctx.state.poster_src = ""
    ctx.state.game_icon_src = ""
    ctx.state.logo_src = ""
    ctx.state.title = ""
    ctx.state.status = ""


def _render(ctx: Any) -> None:
    shared = _shared()
    appid = shared.appid_of(ctx.config)
    if appid <= 0:
        _idle(ctx, "Pick a game")
        return

    game = shared.game_by_appid(appid)
    name = game["name"] if game else f"App {appid}"
    launching = (time.monotonic() - _launched_at.get(appid, -1e9)) < _FLASH_S
    show_title = _truthy(ctx.config.get("show_title", False))
    if launching:
        status = "Launching…"
    elif game is None:
        status = "Not installed"
    else:
        status = ""

    # Preferred artwork first; anything missing from Steam's cache falls
    # through to the next kind so the key never ends up blank.
    face = str(ctx.config.get("face", "icon")).lower()
    poster = icon = logo = ""
    if face == "poster":
        poster = shared.ensure_poster(appid, ctx.storage_path)
    elif face == "logo":
        logo = shared.ensure_logo(appid, ctx.storage_path)
    if not (poster or logo):
        icon = shared.ensure_icon(appid, ctx.storage_path)

    ctx.state.poster_src = poster
    ctx.state.game_icon_src = icon
    ctx.state.logo_src = logo
    ctx.state.status = status
    ctx.state.icon_src = _ICON

    if poster:
        ctx.state.title = name if show_title else ""
        template = "launch_game_titled" if (show_title or status) else "launch_game"
        if str(ctx.config.get("poster_fit", "cover")).lower() == "contain":
            template += "_contain"
    elif logo:
        ctx.state.title = name if show_title else ""
        template = "launch_game_logo_titled" if (show_title or status) else "launch_game_logo"
    elif icon:
        ctx.state.title = name if show_title else ""
        template = "launch_game_icon_titled" if (show_title or status) else "launch_game_icon"
    else:
        ctx.state.title = name
        template = "launch_game_text"
    ctx.state._template = template


def on_load(ctx: Any) -> None:
    _idle(ctx, "Steam")


def on_poll(ctx: Any, interval: int = 1000) -> None:
    _render(ctx)


def on_press(ctx: Any) -> None:
    shared = _shared()
    appid = shared.appid_of(ctx.config)
    result = shared.launch_game(appid)
    if result.get("success"):
        _launched_at[appid] = time.monotonic()
    ctx.action_result = result
    _render(ctx)
