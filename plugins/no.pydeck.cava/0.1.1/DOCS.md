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
| Audio | Input | Passed to cava's `[input] method`. *Auto* lets cava pick, and is the safe choice — see below. |
| Audio | Sensitivity | cava's `sensitivity` (100 = default). Auto-sensitivity stays on. |
| Audio | Response | The face refreshes 5× a second while cava produces 30 frames; *peak* keeps the loudest of them, *average* smooths, *latest* shows the last one. |
| Label | Show the button title | Draws the button's Title under the bars. |

The background is the button colour, or the gradient from the colour picker.

## How it runs

One cava process is started per distinct (bars, input, sensitivity) setting the
first time a key asks for a frame, and terminated after 20 seconds without one.
Its config is a temporary file; your own `~/.config/cava/config` is never read
or touched.

## Inputs your cava may not have

cava can only use the inputs its packager compiled in, and distributions
differ: Arch's build has PipeWire, Fedora's does not. Asked for one it lacks,
cava refuses to start rather than falling back, so a key set to a missing
input would simply be dead.

Choosing an input this build does not have is therefore not fatal — the key
comes up on cava's own default input instead, which on a PipeWire desktop
reaches it through the PulseAudio interface anyway. To see what yours has:

```bash
ldd "$(command -v cava)" | grep -E 'pipewire|pulse|asound'
```

*ALSA* is different: it needs the `snd_aloop` loopback module, which is a local
setting rather than a missing feature, so the key says `no alsa loopback` and
leaves it to you (`sudo modprobe snd_aloop`) rather than quietly switching.

When cava cannot start at all the key shows the reason in as many characters as
fit — `no pulseaudio`, `no audio device` — and retries every five seconds.

`no pulseaudio` on a machine where audio plainly works usually means PyDeck
itself has no session to reach it through: its installer writes a systemd
*system* unit, and those start without `XDG_RUNTIME_DIR`, which is the only
place the PulseAudio client library looks for its socket. This plugin fills
that in with `/run/user/<uid>` on its own, so it is only worth checking if the
message persists:

```bash
systemctl show -p Environment pydeck.service
ls /run/user/$(id -u)/pulse/native
```
