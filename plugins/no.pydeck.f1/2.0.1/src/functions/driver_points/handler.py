"""F1 Driver Points — driver championship position, points, and headshot."""

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

get_or_refresh_standings = _shared.get_or_refresh_standings
fetch_driver_headshot = _shared.fetch_driver_headshot


def on_load(ctx: Any) -> None:
    ctx.state._template = "driver_points"
    ctx.state.driver_code = ""
    ctx.state.driver_img = ""
    ctx.state.driver_info = ""
    ctx.state.driver_info_class = "driver-info"


def on_poll(ctx: Any, interval: int = 3600000) -> None:
    ctx.state._template = "driver_points"
    driver_id = ctx.config.get("driver_id", "")

    if not driver_id:
        ctx.state.driver_code = ""
        ctx.state.driver_info = "Pick a driver"
        ctx.state.driver_info_class = "driver-info"
        ctx.state.driver_img = ""
        return

    standings = get_or_refresh_standings()
    entry = next(
        (e for e in standings if e["Driver"]["driverId"] == driver_id), None
    )
    if entry is None:
        ctx.state.driver_code = ""
        ctx.state.driver_info = "Not found"
        ctx.state.driver_info_class = "driver-info"
        ctx.state.driver_img = ""
        return

    driver = entry["Driver"]
    pts = entry.get("points", "0")
    pos = entry.get("position", "?")
    if ctx.config.get("show_driver_code", True):
        ctx.state.driver_code = driver.get(
            "code", driver.get("familyName", "")[:3].upper()
        )
    else:
        ctx.state.driver_code = ""

    show_pos = ctx.config.get("show_driver_position", True)
    show_pts = ctx.config.get("show_driver_points", True)
    show_gap = ctx.config.get("show_points_from_leader", False)

    parts = []
    if show_pos:
        parts.append(f"#{pos}")
    if show_pts:
        parts.append(f"{pts}pts")
    if show_gap and standings:
        leader_pts = float(standings[0].get("points", 0))
        gap = float(pts) - leader_pts
        if gap == 0:
            parts.append("(L)")
        else:
            parts.append(f"({int(gap)})")

    ctx.state.driver_info = "  ".join(parts) if parts else ""
    wide = show_gap and show_pos and show_pts
    ctx.state.driver_info_class = "driver-info-sm" if wide else "driver-info"
    ctx.state.driver_img = fetch_driver_headshot(
        driver_id, ctx.storage_path, ctx.plugin_name
    )
