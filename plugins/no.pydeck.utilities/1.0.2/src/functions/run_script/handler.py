"""PDK handler for `run_script`."""

from __future__ import annotations

import sys
from typing import Any

from lib.plugin_id import python_import_module_name

_ICON = "assets/icons/run_script.svg"


def _shared_mod(plugin_name: str) -> Any:
    return sys.modules[python_import_module_name("pdk_plugin_", plugin_name)]


def on_load(ctx: Any) -> None:
    ctx.state._template = "run_script"
    ctx.state.icon_src = _ICON


def on_press(ctx: Any) -> None:
    ctx.action_result = _shared_mod(ctx.plugin_name).run_script(dict(ctx.config))


def on_poll(ctx: Any, interval: int = 250) -> None:
    mod = _shared_mod(ctx.plugin_name)
    result = mod.poll_run_script(dict(ctx.config))
    if not isinstance(result, dict):
        return
    if result:
        ctx.action_result = result
    du = result.get("display_update")
    if isinstance(du, dict) and "image" in du:
        if du.get("image") is None:
            ctx.state.icon_src = _ICON
        else:
            ctx.state.icon_src = str(du["image"])
