"""Roulette — spin the wheel, land on a number.

The wheel itself carries no numbers, so nothing has to line up: the press
decides the result, the spin is a fixed animation keyed off the press
timestamp, and the number pops up on the hub as the wheel comes to rest.
"""

from __future__ import annotations

import random
import time
from typing import Any

# The reds of a real wheel. Everything from 1 to 36 that is not in here is
# black, and the zeroes are green.
RED_NUMBERS = frozenset({
    1, 3, 5, 7, 9, 12, 14, 16, 18,
    19, 21, 23, 25, 27, 30, 32, 34, 36,
})

# The disc these land on sits over a near-black wheel, so "black" here is a
# shade lighter than the wheel bed — a true black disc would read as a hole.
RED = "#d02f2f"
BLACK = "#23232b"
GREEN = "#17924f"
RING = "#f0d98a"


def _colour_of(number: str) -> str:
    if number in ("0", "00"):
        return GREEN
    return RED if int(number) in RED_NUMBERS else BLACK


def _pockets(ctx: Any) -> list:
    """The numbers on the wheel this button spins, as strings.

    American wheels add a second zero, which is exactly what makes them worse
    odds — hence the setting rather than a fixed layout.
    """
    numbers = [str(n) for n in range(0, 37)]
    if str(ctx.config.get("wheel_type", "european")).lower() == "american":
        numbers.append("00")
    return numbers


def _show(ctx: Any, number: str) -> None:
    ctx.state.number = number
    ctx.state.result_color = _colour_of(number)
    ctx.state.result_ring = RING


def on_load(ctx: Any) -> None:
    # No spin yet: an empty number draws nothing, and a transparent disc
    # leaves the wheel bare until the first press.
    ctx.state.spin_at = "0"
    ctx.state.number = ""
    ctx.state.result_color = "transparent"
    ctx.state.result_ring = "transparent"


def on_press(ctx: Any) -> None:
    number = random.choice(_pockets(ctx))
    _show(ctx, number)
    ctx.state.spin_at = f"{time.monotonic():.3f}"
    colour = {RED: "red", BLACK: "black", GREEN: "green"}[ctx.state.result_color]
    ctx.action_result = {"message": f"Roulette — {number} {colour}"}
