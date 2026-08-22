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

| Option | Description |
|:---|:---|
| Name / Title | Show the label row (on by default). |

### HA Display

Read-only view of an entity's current value — useful for sensors.

Shows the value with its unit (`21.5 °C`, `1013 hPa`). Pressing forces an
immediate refresh. Long values automatically drop a font size to stay on one line.

| Option | Description |
|:---|:---|
| Entity Icon | Show the entity's icon above the value. |
| Name / Title | Show the label row below the value (off by default). |

## Naming a button

The label row is the button's own **Title** field, so you can name a button
whatever you like instead of living with Home Assistant's entity name.

- Leave **Title** empty and the button shows the entity's friendly name
  (`Bedroom Power Plug`).
- Type something into **Title** and that wins (`Bedside`).
- Untick **Name / Title** to drop the row entirely and show just the icon and
  state.

Keep custom titles short. The label is a single line and **clips rather than
scrolls** — there is room for roughly 10-12 characters at the default size.
That is the main reason to set one: entity names are usually far too long.

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
