"""F1 Constructor Points — constructor championship position and points."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "pdk_f1_shared", str(_ROOT / "shared.py"),
)
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)

get_or_refresh_constructor_standings = _shared.get_or_refresh_constructor_standings
TEAM_CODES = _shared.TEAM_CODES
TEAM_COLORS = _shared.TEAM_COLORS


def on_load(ctx: Any) -> None:
    ctx.state._template = "constructor_points"
    ctx.state.team_code = "F1"
    ctx.state.team_info = ""
    ctx.state.team_bg_color = "#e10600"


def on_poll(ctx: Any, interval: int = 3600000) -> None:
    ctx.state._template = "constructor_points"
    constructor_id = ctx.config.get("constructor_id", "")

    if not constructor_id:
        ctx.state.team_code = "F1"
        ctx.state.team_info = "Pick a team"
        ctx.state.team_bg_color = "#e10600"
        return

    standings = get_or_refresh_constructor_standings()
    entry = next(
        (
            e
            for e in standings
            if e["Constructor"]["constructorId"] == constructor_id
        ),
        None,
    )
    if entry is None:
        ctx.state.team_code = "?"
        ctx.state.team_info = "Not found"
        ctx.state.team_bg_color = "#e10600"
        return

    pts = entry.get("points", "0")
    pos = entry.get("position", "?")
    ctx.state.team_code = TEAM_CODES.get(
        constructor_id, constructor_id[:3].upper()
    )
    ctx.state.team_info = f"#{pos}  {pts}pts"
    ctx.state.team_bg_color = TEAM_COLORS.get(constructor_id, "#e10600")
