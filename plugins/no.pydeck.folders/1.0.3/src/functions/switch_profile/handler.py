"""PDK handler for `switch_profile`."""

from __future__ import annotations

import sys
from typing import Any

from lib.plugin_id import python_import_module_name

_ICON = "assets/icons/profile_switch.png"


def _shared_mod(plugin_name: str) -> Any:
    return sys.modules[python_import_module_name("pdk_plugin_", plugin_name)]


def on_load(ctx: Any) -> None:
    ctx.state._template = "switch_profile"
    ctx.state.icon_src = _ICON


def on_press(ctx: Any) -> None:
    ctx.action_result = _shared_mod(ctx.plugin_name).switch_profile(dict(ctx.config))
