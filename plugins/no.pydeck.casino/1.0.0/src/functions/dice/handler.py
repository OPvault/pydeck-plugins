"""Dice — one six-sided die, rolled by the press.

The press picks a number and writes the seven pip colours that spell it out;
the tumble that gets there is pure CSS, keyed off the press timestamp. See
``src/shared.css`` for how that clock trick works.
"""

from __future__ import annotations

import random
import time
from typing import Any

# Slot order is the one the stylesheet uses: four corners, two mid-sides, the
# centre. A slot that is not lit paints nothing rather than painting the die's
# own colour, so the ivory gradient underneath stays a gradient.
SLOTS = ("tl", "tr", "ml", "mr", "bl", "br", "c")
PIP_ON = "#1b1f27"
PIP_OFF = "transparent"

FACES = {
    1: ("c",),
    2: ("tl", "br"),
    3: ("tl", "c", "br"),
    4: ("tl", "tr", "bl", "br"),
    5: ("tl", "tr", "c", "bl", "br"),
    6: ("tl", "tr", "ml", "mr", "bl", "br"),
}

RESTING_FACE = 6


def _show(ctx: Any, value: int) -> None:
    lit = FACES[value]
    for slot in SLOTS:
        ctx.state["pip_" + slot] = PIP_ON if slot in lit else PIP_OFF


def on_load(ctx: Any) -> None:
    # Zero is "the roll finished long ago", which leaves every animation
    # resting on its last keyframe: a still die showing RESTING_FACE.
    ctx.state.roll_at = "0"
    _show(ctx, RESTING_FACE)


def on_press(ctx: Any) -> None:
    value = random.randint(1, 6)
    _show(ctx, value)
    # Three decimals is a fifteenth of a frame — far finer than the tick that
    # will read it, and short enough to stay a plain decimal in the CSS.
    ctx.state.roll_at = f"{time.monotonic():.3f}"
    # Reported as a plain value, not as ``message``: the editor pops a toast
    # for every press that returns one, and a game is pressed over and over.
    # The manifest's log_format turns this into the event-log line instead.
    ctx.action_result = {"roll": value}
