# Casino

Three games of chance, one per button. Press and watch: the die tumbles, the
wheel spins, the coin turns over — and each one comes to rest on whatever it
landed on.

## Functions

| Function | What a press does |
|:---|:---|
| **Dice** | Rolls one six-sided die. The die tumbles through five faces and settles on the number it rolled, 1–6. |
| **Roulette** | Spins the wheel and runs the ball the other way round it. When the wheel stops, the winning number pops up on a disc over the hub — red, black, or green for a zero. |
| **Coin Flip** | Turns a coin end over end — four turns, each slower than the last — and lands on **HEADS** or **TAILS**. |

Every result is drawn fresh from Python's `random` at the moment of the press.
Nothing is weighted, and nothing is remembered between presses.

## Settings

**Roulette → Wheel** picks the layout the number is drawn from:

- **European (0–36)** — 37 pockets, one green zero.
- **American (0, 00–36)** — 38 pockets, two green zeroes, and correspondingly
  worse odds. The wheel drawn on the button has twelve pockets either way; it
  is decoration, not the layout being played.

Dice and Coin Flip have nothing to configure.

## What the press log shows

Each press reports its result to the editor's event log — `Button 3 — rolled
5`, `landed on 17 black`, `landed on HEADS` — so a game is readable even while
the button is still animating. It deliberately does **not** report a
`message`: the editor pops a toast for every press that returns one, which a
button you press over and over should not do.

## Two buttons, one game

PDK keeps handler state per *function*, not per button, so two buttons running
**the same** game share a result: press one and both faces show the roll. Two
buttons running *different* games (a die and a coin, say) are completely
independent. If you want two dice, expect them to agree.

## How the coin turns

Nothing in the renderer has a third dimension, so the coin is four discs of
the same width and falling height stacked on one centre line, lit one at a
time: face-on, two foreshortened, and the milled edge seen straight on. Cut
between them in order and a coin turns over. The letter on the face shrinks
and darkens into the edge's own colour as its side goes away, which is what
keeps the last pixel of a hidden face from showing.

## How the animation works

There is no animation loop in the Python here. PDK re-renders an animated
button around 15 times a second and hands the stylesheet the current clock, so
every frame is a function of time — while handler state only changes on a
press. The handlers exploit that: a press writes its own timestamp into the
`animation` delay slot, which turns "time since the process started" into
"time since the press", and writes the result into the final keyframe. The
animation therefore starts on the press, runs exactly once, and freezes on the
result for good. `src/shared.css` documents the technique in full.
