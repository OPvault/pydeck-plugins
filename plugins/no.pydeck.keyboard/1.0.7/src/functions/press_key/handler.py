"""PDK handler for `press_key`."""

from __future__ import annotations

import sys
from typing import Any

from lib.plugins.ids import python_import_module_name


def _shared_mod(plugin_name: str) -> Any:
    return sys.modules[python_import_module_name("pdk_plugin_", plugin_name)]


def on_load(ctx: Any) -> None:
    ctx.state._template = "press_key"


def on_press(ctx: Any) -> None:
    _shared_mod(ctx.plugin_name).press_key(dict(ctx.config))
