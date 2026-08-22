# Media Control

Transport and volume keys for any Linux desktop — no account, no API key, no
login. The plugin talks to whatever is already running on your machine.

---

## How it works

| Job | Tool | Notes |
|:---|:---|:---|
| Play / pause / next / previous | `playerctl` | Over MPRIS, the standard D-Bus interface media apps expose |
| Volume and mute | `pactl`, else `amixer` | Acts on the **default sink** (`@DEFAULT_SINK@` / `Master`) |
| Last resort | `xdotool` | Sends the `XF86Audio*` media keys instead |

The button faces are drawn by PDK, so they show live state: the Play/Pause key
draws a pause glyph while something is playing, the volume keys can show the
current volume percentage, and the mute key turns red while the sink is muted.

---

## Prerequisites

Install the tools you need for the keys you plan to use:

=== "Arch"

    ```bash
    sudo pacman -S playerctl libpulse   # libpulse provides pactl
    ```

=== "Debian / Ubuntu"

    ```bash
    sudo apt install playerctl pulseaudio-utils
    ```

=== "Fedora"

    ```bash
    sudo dnf install playerctl pulseaudio-utils
    ```

`pactl` also works on PipeWire (via `pipewire-pulse`), which is the default on
most current distributions. `amixer` (from `alsa-utils`) is used only when
`pactl` is missing.

Check what you have:

```bash
playerctl --list-all      # the MPRIS players the plugin can see
pactl get-sink-volume @DEFAULT_SINK@
```

---

## The keys

| Function | What it does |
|:---|:---|
| **Play** | Start playback |
| **Pause** | Pause playback |
| **Play/Pause** | Toggle — the glyph follows the player's real status |
| **Next Track** | Skip forward |
| **Previous Track** | Skip back |
| **Volume Up** | Raise the default sink by the configured step |
| **Volume Down** | Lower it by the same step |
| **Toggle Mute** | Mute / unmute the default sink |

---

## Settings

### Player

Every transport key has an optional **Player** field. Leave it empty to target
**all** MPRIS players (`playerctl --all-players`); the plugin then follows
whichever one is actually playing. Fill it in with a player name — `spotify`,
`firefox`, `mpv` — to pin the key to that app. The names come from
`playerctl --list-all`; a `firefox.instance_1_2492`-style id matches on its
`firefox` prefix.

### Track Label (Play/Pause)

Off by default. Choose **Song**, **Song - Artist** or **Artist** to draw the
now-playing line under the glyph. Long titles scroll.

### Volume Step (%)

How much one press moves the volume, `1`–`50`, default `5`.

### Show Volume % (Volume Up / Volume Down)

Draws the sink's current volume under the glyph, refreshed every 3 seconds.

### Toggle Mute icons

The mute key ships two icons — a speaker and a crossed-out speaker — and
declares them as **display states**, so the button editor offers a state
selector under the icon preview. Pick your own image for either state from the
gallery; the plugin keeps drawing the background and the muted colour.

---

## Upgrading from Media Control 1.x

The classic plugin was a flat `plugin.py`; this is a PDK plugin, so the button
face comes from a template rather than from a static image.

- **Button images.** 1.x set a `default_display.image` per function. The PDK
  version draws its own glyph instead, and a gallery image on the button would
  suppress that face — so the gallery is off for every key except **Toggle
  Mute**, which uses it for per-state icons.
- **Action Builder steps.** 1.x also exported title-cased `Play` and `Pause`
  aliases for action configs. PDK dispatches by the function name in the
  manifest, so those aliases are gone — use `play` and `pause`.
- **`player` is now a UI field.** 1.x read a `player` key from the button
  config but never offered a way to set it.

---

## Troubleshooting

**Nothing happens on a transport key.** Run `playerctl --list-all`. An empty
list means no app is exposing MPRIS — browsers usually need a tab that has
actually started playing. If your app never appears, install `xdotool` so the
plugin can fall back to media keys.

**The Play/Pause glyph never changes.** The status probe uses the same
`playerctl` target as the press. If you set **Player** to a name that does not
match, the key falls back to the neutral combined glyph.

**Volume keys do nothing.** Check `pactl get-sink-volume @DEFAULT_SINK@`. If
`pactl` is missing the plugin tries `amixer get Master`; if neither exists you
need `xdotool` for the media-key fallback, and the volume % will stay blank
because there is nothing to read it from.

**Volume changes the wrong device.** The plugin always acts on the *default*
sink. Change the default in your sound settings (or `pactl set-default-sink`).
