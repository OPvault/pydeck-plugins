# Home Assistant

Control and monitor Home Assistant entities from your Stream Deck.

## Setup

1. In Home Assistant, open your **profile** → **Security** → **Long-Lived Access Tokens**
   and choose **Create Token**. Copy it — Home Assistant only shows it once.
2. In PyDeck, go to **Settings → Credentials → Home Assistant** and fill in:
   - **Home Assistant URL** — e.g. `http://192.168.1.7:8123`. If you leave the
     port off, `:8123` is assumed.
   - **Long-Lived Access Token** — the token from step 1.
3. Drag **HA Toggle** or **HA Display** onto a button.
4. Pick a **Domain** to narrow the list (or leave it on *All*), then pick an **Entity**.

## Buttons

### HA Toggle

Flips an entity on or off and mirrors its real state.

The button face shows the entity's icon, its name, and `ON` / `OFF`. Pressing
calls `homeassistant.toggle` and immediately shows the assumed new state so the
deck feels instant; the poll loop reconciles with Home Assistant a few seconds
later, so a service call that silently fails corrects itself rather than lying.

An entity Home Assistant reports as `unavailable` shows **N/A** rather than
`OFF` — the device may well be on and simply unreachable.

**Display options**

| Option | Default | Description |
|:---|:---|:---|
| Entity Icon | on | Show the entity's icon. |
| Name / Title | on | Show the label row — your Title, or the entity name. |
| On / Off State | on | Show the `ON` / `OFF` / `N/A` line. Turn off for an icon-only button. |
| Highlight When On | on | Tint the icon and state amber while the entity is on. Off keeps everything neutral. |

Hidden rows give their space back to the icon, so a button with the state and
label both off draws a large icon and nothing else.

### HA Display

Read-only view of an entity's current value — useful for sensors.

Shows the value with its unit (`10.3°C`, `5300 MHz`). Pressing forces an
immediate refresh.

The value is sized to fit: short readings render large and step down through
four sizes as they get longer, because PDK text is single-line and neither
wraps nor auto-shrinks.

**Display options**

| Option | Default | Description |
|:---|:---|:---|
| Entity Icon | on | Show the entity's icon above the value. |
| Value | on | Show the reading itself. Turn off for an icon-and-name button. |
| Unit | on | Append the unit — `10.3°C` versus `10.3`. Hidden when **Value** is off. |
| Name / Title | off | Show the label row below the value. |
| Highlight When On | on | Tint the icon amber for entities that report an on-like state. |

## Naming a button

The label row is the button's own **Title** field, so you can call a button
whatever you like instead of living with Home Assistant's entity name.

| Title field | Button shows |
|:---|:---|
| *(empty)* | the entity's friendly name — `Bedroom Power Plug` |
| `Bedside` | `Bedside` |

Untick **Name / Title** to drop the row entirely and show just the icon and
state.

### How it works

The templates use PDK's `<buttonlabel>` element with the entity name as its
body:

```xml
<buttonlabel class="name">{name}</buttonlabel>
```

PyDeck fills `<buttonlabel>` with the user's Title *before* it interpolates
`{name}` from plugin state. So a Title you set wins, and an empty one falls
through to whatever the handler put in `ctx.state.name` — here, the entity's
`friendly_name`. No handler code is involved in the override.

Because of that ordering, `default_display.text` is deliberately `""` in
`manifest.json`. A non-empty default would count as a Title on every new
button and permanently hide the entity-name fallback.

!!! warning "Keep custom titles short"
    The label is a single line and **clips rather than scrolls** —
    `<buttonlabel>` is not a marquee, and PyDeck's title scroller does not
    apply to it. Roughly 10-12 characters fit. That is the main reason to set
    one: entity names are usually far too long.

## Icons

Icons come from the entity's own `icon` attribute when it has one, otherwise
they are chosen from the entity's domain and `device_class`. They are fetched
from the Material Design Icons CDN and rasterized into
`~/.local/share/pydeck/storage/no.pydeck.home-assistant/icons/`, so each icon is
only downloaded once. Rendering uses `cairosvg` when it is installed and falls
back to a bundled set of hand-drawn shapes when it is not.

## Troubleshooting

| Button shows | Meaning |
|:---|:---|
| `Pick an entity` | No entity selected yet — open the button's settings. |
| `Unknown entity: …` | The entity no longer exists in Home Assistant. |
| `401 Unauthorized` | The token is wrong or was revoked — create a new one. |
| `Connection failed` | PyDeck cannot reach the URL. Check the host and port. |
| `N/A` | Home Assistant reports the entity as unavailable. |
