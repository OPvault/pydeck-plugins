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
| Audio | Input method | Passed to cava's `[input] method`. *Auto* lets cava pick, and is the safe choice — see below. |
| Audio | Audio source | Which device to listen to — see [Picking the right line](#picking-the-right-line). *Auto* follows whatever is making noise. |
| Audio | Sensitivity | cava's `sensitivity` (100 = default). Auto-sensitivity stays on. |
| Audio | Response | The face refreshes 5× a second while cava produces 30 frames; *peak* keeps the loudest of them, *average* smooths, *latest* shows the last one. |
| Label | Show the button title | Draws the button's Title under the bars. |

The background is the button colour, or the gradient from the colour picker.

## Picking the right line

On a machine that splits its audio there is no single right answer. A GoXLR,
for example, gives Game, Music, Chat, System and Sample a sink of their own:
music goes out on one of them and the system default is another, so a key
pointed at the default stays flat while the track is plainly playing.

**Audio source** lists what the machine actually has, named the way your
desktop names it:

| | |
|---|---|
| `GoXLRMini Music (output)` | a sink's **monitor** — what is being played *out* of it. This is what a visualiser wants. |
| `GoXLRMini System (output) · default` | the monitor of the system default sink, i.e. what *Auto* would have picked. |
| `GoXLRMini Chat Mic (input)` | a real capture device — a microphone or a line in. |

Outputs are listed first. The list follows the **Input method**: *PipeWire*,
*PulseAudio* and *Auto* share one set of names, because a sink's monitor is the
same string to all three, while *ALSA* lists `hw:` capture devices instead —
the only spelling its input understands. Changing the method therefore clears
the source; pick the method first.

### Auto follows the audio

Left on **Auto**, the key does not settle for the system default — it looks for
the line that is actually making noise.

1. The candidates are the sinks with a stream open on them, the newest stream
   first. The default sink's monitor goes to the front when it is one of them,
   and is the last entry either way.
2. While the chosen line has sound, nothing changes.
3. Once it has been silent for about two and a half seconds, the key steps to
   the next candidate, giving each two seconds to prove itself, and stops as
   soon as one is audible.
4. With nothing playing anywhere the list is just the default sink's monitor,
   so that is where a quiet machine comes to rest — which is what cava would
   have picked unaided.

Step 3 steps rather than picks a favourite on purpose: a stream being *open*
says nothing about it making noise. `speech-dispatcher` keeps an uncorked
stream on the chat sink permanently and is silent on every one of those
seconds, and a key that simply chose the most promising candidate would sit on
it forever. Visiting each in turn is what makes the silence self-correcting.

Paused players are skipped outright — a corked stream is not something to
watch — so pausing Spotify sends the key hunting for whatever else is on.

If you want a key nailed to one line regardless of what else is playing, choose
that line explicitly instead of leaving it on *Auto*. Auto is unavailable under
the *ALSA* input method, which has no way to say which device is busy; there it
means cava's own default, as before.

If the chosen device is unplugged or renamed, the key shows `input missing`.
That check exists because cava itself says nothing: pointed at a source that is
not there it starts, captures nothing and reports zeros indefinitely, which on
a key looks exactly like a quiet room. When the device list cannot be read at
all — no `pactl`, or a PyDeck with no way to reach the session — the key is
left alone rather than blamed.

## How it runs

One cava process is started per distinct (bars, input, source, sensitivity)
setting the first time a key asks for a frame, and terminated after 20 seconds
without one. Its config is a temporary file; your own `~/.config/cava/config`
is never read or touched.

The device list comes from `pactl` (or `/proc/asound/pcm` for ALSA) and is
cached for ten seconds, so opening the editor does not spawn one process per
keystroke. Auto's search asks `pactl` which sinks have streams on them, and
only while the current line is silent — a key watching music makes no such
calls at all. A line Auto has moved off is torn down within a couple of
seconds rather than being left to the twenty-second idle timer, so a hunt does
not stack up a cava per candidate.

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
