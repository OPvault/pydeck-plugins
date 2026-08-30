# System Monitor

Six readouts for what the machine is doing, all reading the kernel directly —
no extra Python packages, no daemon.

## Actions

| Action | What it shows |
| --- | --- |
| **CPU** | Usage, temperature, clock speed and load average. |
| **RAM** | Memory in use, what is left, and swap. |
| **GPU** | Utilisation, temperature, VRAM and board power. |
| **Disk** | How full a mount point is, and what is free on it. |
| **Network** | Live download and upload rates, per interface or summed. |
| **Battery** | Charge, draw and estimated time left. |

Every face is the same four parts — a header, one big value, a sub line and a
bar — so a row of them reads as one instrument panel rather than six.

## Layouts

**Layout** decides the geometry:

- *Stat* — header, value, sub line and a bar underneath. The default.
- *Minimal* — the value alone, as large as the key allows, over a hairline bar.
- *Gauge* — a big value and sub line over a thick bar along the bottom edge.
- *Split* — the text ranged left with the bar standing vertically beside it.
- *Graph* — the value over a plot of the last 14 readings.

The history plot is kept per button, so two Disk keys watching different mount
points plot their own line.

## Themes

18 palettes: Classic, Carbon, Slate, Light, Paper, Mono, Terminal, LCD, Amber,
Neon, Midnight, Ocean, Sunset, Blueprint, Nord, Dracula, Gruvbox and Solarized.
Each ships its own background, ink and threshold ramp, so a warning reads as a
warning in Nord without turning into GitHub red.

**Palette** overrides where the colours come from:

- *Theme* — the palette the theme ships.
- *Button colour* — the button's own colour or gradient, from the editor's
  colour picker.
- *Custom* — your own background, value and accent hex values.

The custom **value colour** doubles as the ramp's all-clear entry, so it is what
the face shows most of the time; the warn and critical gates still take the
value over when they trip. The **accent colour** is what the bar falls back to
when the threshold tint is off.

With either of the last two palettes, ink that would land too close to the
background is swapped for a legible substitute, so a pale button colour does
not leave you with white text on white.

## Readings

**Main Value** and **Sub Line** are independent — put usage on the face and the
temperature underneath, or the other way round, or drop the sub line entirely.
Whatever you choose, **the bar always tracks the load percentage** for that
readout (CPU usage, memory used, GPU utilisation, disk fullness, battery charge,
network rate against the full-scale you set). That is what keeps a row of keys
comparable at a glance.

## Thresholds

**Warn At** and **Critical At** are the two gates that tint the value, the bar
and each history bar. They are percentages of the reading the bar tracks, and
they default to something sensible per readout — 60/85 for CPU and GPU, 70/90
for RAM, 75/90 for disk. Battery reads them the other way round: 30/15 means
amber below 30% and red below 15%.

**Threshold Tint** picks what drives the colour:

- *Follow the reading* — the percentage the bar tracks. The default.
- *Follow the temperature* — CPU and GPU only, using the two °C gates.
- *Off* — leave the value in the theme's own ink.

## Data sources

Each readout tries the kernel first and a command-line tool only if that fails.
**Data Source** pins it to one when auto-detection picks wrong:

| Readout | Order tried |
| --- | --- |
| CPU usage | `/proc/stat` → `vmstat` → `mpstat` → `top` |
| CPU temperature | `/sys/class/hwmon` → `/sys/class/thermal` → `sensors` |
| RAM | `/proc/meminfo` → `free` → `top` |
| Disk | `os.statvfs` → `df` |
| GPU | `nvidia-smi` → `rocm-smi` → `/sys/class/drm` |
| Network | `/proc/net/dev` |
| Battery | `/sys/class/power_supply` |

A rate is a difference, so the Network readout shows `0B/s` on its first poll
after a restart — there is nothing yet to subtract from. **Bar Full Scale** is
what the bar reads as 100%; set it to your link speed.

`rocm-smi` reports VRAM as a percentage rather than in bytes, so an AMD card
shows *VRAM* as a percentage where an NVIDIA one shows used / total.
