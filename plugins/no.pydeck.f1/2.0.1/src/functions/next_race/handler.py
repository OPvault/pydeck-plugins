"""F1 Next Race — countdown to the next Formula 1 session."""

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

get_or_refresh_meeting = _shared.get_or_refresh_meeting
find_target_session = _shared.find_target_session
countdown_text = _shared.countdown_text
download_circuit_image = _shared.download_circuit_image
clear_session_cache = _shared.clear_session_cache
country_flag = _shared.country_flag
SESSION_SHORT = _shared.SESSION_SHORT


def on_load(ctx: Any) -> None:
    ctx.state._template = "next_race"
    ctx.state.track_src = ""
    ctx.state.session_label = ""
    ctx.state.track_label = ""
    ctx.state.countdown = "..."
    ctx.state.countdown_class = "countdown"


def on_press(ctx: Any) -> None:
    clear_session_cache()
    _poll(ctx)


def on_poll(ctx: Any, interval: int = 1000) -> None:
    _poll(ctx)


def _poll(ctx: Any) -> None:
    ctx.state._template = "next_race"
    meeting = get_or_refresh_meeting()

    if meeting is None:
        ctx.state.countdown = "Off Season"
        ctx.state.countdown_class = "countdown"
        ctx.state.session_label = ""
        ctx.state.track_label = ""
        ctx.state.track_src = ""
        return

    session = find_target_session(meeting, ctx.config)
    target = session if session is not None else meeting
    ctx.state.countdown = countdown_text(target, ctx.config)
    ctx.state.countdown_class = (
        "countdown-sm" if ctx.config.get("show_seconds", False) else "countdown"
    )
    raw_name = target.get("session_name", "")
    if ctx.config.get("show_session_label", True):
        ctx.state.session_label = SESSION_SHORT.get(raw_name, raw_name)
    else:
        ctx.state.session_label = ""

    if ctx.config.get("show_track_label", True):
        track_name = meeting.get("circuit_short_name", "")
        if ctx.config.get("show_country_flag", False):
            flag = country_flag(meeting.get("country_code", ""))
            ctx.state.track_label = f"{flag} {track_name}" if flag else track_name
        else:
            ctx.state.track_label = track_name
    else:
        ctx.state.track_label = ""

    ctx.state.track_src = download_circuit_image(
        meeting, ctx.storage_path, ctx.plugin_name
    )
