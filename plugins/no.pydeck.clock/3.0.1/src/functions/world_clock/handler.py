"""World Clock -- the time in another city, with an optional second location."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("pdk_clock_shared", str(_ROOT / "shared.py"))
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _shared
_spec.loader.exec_module(_shared)


def _caption(cfg: dict) -> str:
    custom = str(cfg.get("location_label") or "").strip()
    return custom or _shared.zone_label(str(cfg.get("timezone", "UTC")))


def _pair_state(cfg: dict) -> dict:
    """Two cities stacked on one key: name, time, name, time."""
    style = _shared.apply_colors(
        _shared.digital_style(str(cfg.get("digital_style", "classic"))), cfg,
    )
    rows = []
    for tz_key, label_key in (
        ("timezone", "location_label"), ("timezone_2", "location_label_2"),
    ):
        tz_name = str(cfg.get(tz_key) or "").strip()
        if not tz_name:
            continue
        now = _shared.now_in(tz_name, cfg)
        text, ampm = _shared.format_time(now, cfg)
        if ampm:
            text = f"{text} {ampm}"
        name = str(cfg.get(label_key) or "").strip() or _shared.zone_label(tz_name)
        rows.append((name.upper() if style["upper"] else name, text))

    state = _shared.blank_slots()
    state.update(_shared.decorations(style))
    state.update({
        "_template": "digital",
        "bg": style["bg"],
        "col_y": "0%",
        "col_h": "100%",
    })
    bold = style["wt"] == "bold"
    n = 1
    for i, (name, text) in enumerate(rows[:2]):
        state.update(_shared.slot(
            n, name, style["dim"], _shared.fit_em(name, 90.0, 0.55),
            family=style["ff"], pad_top=4 if i else 0,
        ))
        state.update(_shared.slot(
            n + 1, text, style["fg"],
            _shared.fit_em(text, 84.0, 1.05, bold),
            weight=style["wt"], family=style["ff"],
        ))
        n += 2
    return state


def render(ctx: Any) -> None:
    cfg = ctx.config
    if str(cfg.get("timezone_2") or "").strip():
        state = _pair_state(cfg)
    else:
        now = _shared.now_in(str(cfg.get("timezone", "UTC")), cfg)
        caption = _caption(cfg)
        if str(cfg.get("display_mode", "digital")) == "analog":
            state = _shared.analog_state(now, cfg, caption=caption)
        else:
            state = _shared.digital_state(now, cfg, caption=caption)

    ctx.state.clear()
    ctx.state.update(state)


def on_load(ctx: Any) -> None:
    render(ctx)


def on_poll(ctx: Any, interval: int = 1000) -> None:
    render(ctx)


def on_press(ctx: Any) -> None:
    render(ctx)
