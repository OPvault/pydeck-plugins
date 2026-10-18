"""Coin flip — heads or tails.

The press picks the side and sizes the two faces at rest: the winner ends the
animation at full size, the loser at one pixel. Everything in between — four
turns of a coin drawn as a stack of flattening discs — is the stylesheet's,
timed from the press. See ``src/shared.css``.
"""

from __future__ import annotations

import random
import time
from typing import Any

# The size the winning face comes to rest at, and the size that reads as "not
# on this side of the coin" — one pixel rather than zero, because a font cannot
# be loaded at size 0 at all. That last pixel is still drawn, so the losing
# face is also inked in the coin's own gold and disappears into it.
FACE_SIZE = "25"
FACE_HIDDEN = "1"
INK_SHOWN = "#4a3607"
INK_HIDDEN = "#f0d78e"


def _show(ctx: Any, heads: bool) -> None:
    ctx.state.heads_size = FACE_SIZE if heads else FACE_HIDDEN
    ctx.state.tails_size = FACE_HIDDEN if heads else FACE_SIZE
    ctx.state.heads_ink = INK_SHOWN if heads else INK_HIDDEN
    ctx.state.tails_ink = INK_HIDDEN if heads else INK_SHOWN
    ctx.state.result_text = "HEADS" if heads else "TAILS"


def on_load(ctx: Any) -> None:
    # A blank coin until it is first flipped: both faces hidden, no caption.
    ctx.state.flip_at = "0"
    ctx.state.heads_size = FACE_HIDDEN
    ctx.state.tails_size = FACE_HIDDEN
    ctx.state.heads_ink = INK_HIDDEN
    ctx.state.tails_ink = INK_HIDDEN
    ctx.state.result_text = ""


def on_press(ctx: Any) -> None:
    heads = random.random() < 0.5
    _show(ctx, heads)
    ctx.state.flip_at = f"{time.monotonic():.3f}"
    # A ``message`` key would toast on every flip; log_format in the manifest
    # puts the side in the event log without one.
    ctx.action_result = {"side": ctx.state.result_text}
