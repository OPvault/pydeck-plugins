# Clock

Analog and digital clocks, world clocks and countdown timers.

## Actions

| Action | What it does |
| --- | --- |
| **My Clock** | Your default clock — analog or digital, in any time zone. |
| **World Clock** | Another city's time, with an optional second location on the same key. |
| **Countdown** | A timer on the key. Press to start, press again to pause, press at zero to reset. |

## Appearance

Pick **Digital** or **Analog**, then a style: 16 analog faces (Classic, Railway,
Bauhaus, Chronograph, Neon, Numerals, Blueprint, Gold, Dots, Halo, Skeleton,
Retro, Aviator, Midnight, Minimal, Outline) and 16 digital ones (Classic, Bold,
Light, Mono, LCD, Tiles, Neon, Terminal, Card, Stacked, Headline, Ticker,
Outline, Sunrise, Minimal, Badge).

**Classic** has no palette of its own: it follows the button's own colour or
gradient, so the colour picker in the editor drives the face. Every other theme
keeps its designed palette unless you set **Colors**:

- *Theme palette* — the theme's own colours (Classic still follows the button).
- *Button color* — use the button's colour or gradient on any theme.
- *Custom* — your own background, time and accent hex values.

Whichever you pick, any ink that would land too close to the background is
swapped for a legible substitute, so a pale button colour does not leave you
with white text on white.

## Time and date

- **Time format** — 24-hour or 12-hour with AM/PM.
- **Show seconds** (digital) / **Show second hand** (analog).
- **Show date** with six date formats, and **Show weekday** in short or full form.
- **Custom time format** — a `strftime` pattern such as `%H.%M` or `%I:%M %p`
  that replaces the time readout entirely. This is the escape hatch for
  anything the options above do not cover.

## Countdown durations

The **Duration** field accepts `90` (seconds), `5:00`, `1:30:00`, `25m` or
`1h30m`. **At zero** chooses whether the timer holds at `0:00` or counts up.

Each countdown key keeps its own timer, stored under the plugin's storage
directory so the running total survives a restart and stays in step between the
web grid and the deck.

## Emulated clock (developer)

With **Settings → Developer → Emulated clock** enabled, every clock face renders
a fixed instant instead of the current time, so exported button images are
reproducible. The properties panel gains an **Emulated time** field that
overrides the global value for that button alone — set a different time per key
to shoot a wall of world clocks.

Accepted spellings: `19:43`, `19:43:43`, `2023-02-09 19:43`,
`2023-02-09 19:43:43` (or with a `T` separator). A bare time uses today's date.
The value is the time the face *displays*, whatever zone the button is set to.
