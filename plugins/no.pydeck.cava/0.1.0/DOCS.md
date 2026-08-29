# Cava

A live audio spectrum on a key. The plugin runs [cava](https://github.com/karlstav/cava)
in its raw output mode and draws the bars it reports.

## Requirements

`cava` must be installed and on `PATH` (`pacman -S cava`, `apt install cava`, …).
The face shows *cava not found* until it is.

## Settings

| Group | Setting | What it does |
|---|---|---|
| Shape | Bars | 4 – 32 bars. Fewer bars read better on a 72 px key. |
| Shape | Style | Rise from the bottom, hang from the top, or mirror around the middle. |
| Shape | Gap / Corners | Spacing between bars and their corner shape. |
| Shape | Keep a thin floor | Leave a 2 % stub visible when the input is silent. |
| Colour | Bar colour | *Solid*, a quiet→loud *level gradient*, a *spread* across the bars, or *rainbow*. |
| Audio | Input | Passed to cava's `[input] method`. *Auto* lets cava pick. |
| Audio | Sensitivity | cava's `sensitivity` (100 = default). Auto-sensitivity stays on. |
| Audio | Response | The face refreshes 5× a second while cava produces 30 frames; *peak* keeps the loudest of them, *average* smooths, *latest* shows the last one. |
| Label | Show the button title | Draws the button's Title under the bars. |

The background is the button colour, or the gradient from the colour picker.

## How it runs

One cava process is started per distinct (bars, input, sensitivity) setting the
first time a key asks for a frame, and terminated after 20 seconds without one.
Its config is a temporary file; your own `~/.config/cava/config` is never read
or touched.
