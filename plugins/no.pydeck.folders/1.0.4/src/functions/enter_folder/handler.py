"""PDK handler for `enter_folder`."""

from __future__ import annotations

import sys
from typing import Any

from lib.plugins.ids import python_import_module_name

_ICON = "assets/icons/folder_enter.png"


def _shared_mod(plugin_name: str) -> Any:
    return sys.modules[python_import_module_name("pdk_plugin_", plugin_name)]


def on_load(ctx: Any) -> None:
    ctx.state._template = "enter_folder"
    ctx.state.icon_src = _ICON


def on_press(ctx: Any) -> None:
    ctx.action_result = _shared_mod(ctx.plugin_name).enter_folder(dict(ctx.config))
