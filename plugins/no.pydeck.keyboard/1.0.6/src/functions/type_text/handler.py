"""PDK handler for `type_text`."""

from __future__ import annotations

import sys
from typing import Any

from lib.plugins.ids import python_import_module_name


def _shared_mod(plugin_name: str) -> Any:
    return sys.modules[python_import_module_name("pdk_plugin_", plugin_name)]


def on_load(ctx: Any) -> None:
    ctx.state._template = "type_text"


def on_press(ctx: Any) -> None:
    _shared_mod(ctx.plugin_name).type_text(dict(ctx.config))
