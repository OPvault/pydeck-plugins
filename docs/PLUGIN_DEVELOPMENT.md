# PyDeck Plugin Development Guide

Everything you need to build, test, and ship a PyDeck plugin.

---

## Table of Contents

1. [Quick Start — Hello World](#1-quick-start--hello-world)
2. [Plugin Directory Structure](#2-plugin-directory-structure)
3. [manifest.json Reference](#3-manifestjson-reference)
4. [plugin.py — Writing Functions](#4-pluginpy--writing-functions)
5. [UI Field Types](#5-ui-field-types)
6. [Display States and Toggling](#6-display-states-and-toggling)
7. [Display Polling](#7-display-polling)
8. [Credentials](#8-credentials)
9. [OAuth Integration](#9-oauth-integration)
10. [Custom CSS — style.css](#10-custom-css--stylecss)
11. [Client-Side Popup API — PyDeck.popup](#11-client-side-popup-api--pydeckpopup)
12. [Plugin Images — img/](#12-plugin-images--img)
13. [options.json (Marketplace Metadata)](#13-optionsjson-marketplace-metadata)
14. [Button Types](#14-button-types)
15. [Actions (Multi-Step Sequences)](#15-actions-multi-step-sequences)
16. [REST API Reference](#16-rest-api-reference)
17. [WebSocket Events](#17-websocket-events)
18. [Config and File Paths](#18-config-and-file-paths)
19. [Real-World Plugin Examples](#19-real-world-plugin-examples)
20. [Tips and Best Practices](#20-tips-and-best-practices)

---

## 1. Quick Start — Hello World

The fastest way to see how plugins work. This creates a plugin with one button that prints a greeting.

### Step 1: Create the plugin folder

```
plugins/plugin/hello_world/
```

### Step 2: Create `manifest.json`

```json
{
  "name": "hello_world",
  "version": "1.0.0",
  "description": "A simple greeting plugin",
  "functions": {
    "greet": {
      "label": "Say Hello",
      "description": "Show a greeting message",
      "default_display": {
        "color": "#4a90d9",
        "text": "Hello"
      },
      "ui": [
        {
          "type": "input",
          "id": "name",
          "label": "Your Name",
          "placeholder": "World",
          "default": ""
        }
      ]
    }
  }
}
```

### Step 3: Create `plugin.py`

```python
from __future__ import annotations
from typing import Any, Dict


def greet(config: Dict[str, Any]) -> Dict[str, Any]:
    name = config.get("name") or "World"
    return {
        "success": True,
        "message": f"Hello, {name}!"
    }
```

### Step 4: Done

Restart PyDeck. The "hello_world" plugin appears in the sidebar with a "Say Hello" function. Drag it onto a button and press it. The button text changes to "Hi World!" (or whatever name you configured). The `display_update` key tells the core to update the button's appearance on the Stream Deck and in the web GUI after each press.

---

## 2. Plugin Directory Structure

Every plugin lives under `plugins/plugin/<plugin_name>/`. The folder name **is** the plugin name used everywhere in the system.

```
plugins/plugin/my_plugin/
├── manifest.json          # REQUIRED — metadata, functions, credentials, OAuth
├── plugin.py              # REQUIRED — Python functions called on button press
├── style.css              # Optional — custom CSS loaded automatically
├── options.json           # Optional — marketplace/catalog metadata
├── img/                   # Optional — icon images served via API
│   ├── icon_default.png
│   └── icon_active.png
└── (any other .py files)  # Optional — helper modules imported by plugin.py
```

### Required Files

| File | Purpose |
|:---|:---|
| `manifest.json` | Declares the plugin's name, functions, UI fields, credentials, and OAuth config. The core reads this to discover the plugin and build the GUI. |
| `plugin.py` | Contains the Python functions that get called when buttons are pressed. Each function listed in the manifest must exist here as a top-level callable. |

### Optional Files

| File | Purpose |
|:---|:---|
| `style.css` | Custom CSS rules for your plugin. Automatically scanned and served by the core — no registration needed. |
| `options.json` | Human-friendly metadata for a future plugin marketplace (description, features, tags). |
| `img/` | Image assets served at `/api/plugins/<name>/img/<filename>`. Used for button icons, display states, etc. |
| `*.py` | Additional Python modules. Import them from `plugin.py` using a path insert (see [Spotify example](#spotify-oauth--api-client)). |

---

## 3. manifest.json Reference

The manifest is a JSON object with the following top-level keys:

```json
{
  "name": "my_plugin",
  "version": "1.0.0",
  "description": "What the plugin does",
  "author": "Your Name",
  "credentials": [ ... ],
  "oauth": { ... },
  "permissions": { ... },
  "functions": { ... }
}
```

### Top-Level Fields

| Field | Type | Required | Description |
|:---|:---|:---|:---|
| `name` | string | Yes | Plugin identifier. Must match the folder name. |
| `version` | string | No | Semantic version string (e.g. `"1.0.0"`). |
| `description` | string | No | One-line description shown in the sidebar. |
| `author` | string | No | Plugin author name. |
| `credentials` | array | No | Credential fields shown under **Settings → API** on the web UI. See [Credentials](#8-credentials). |
| `settings` | object | No | Optional category for a plugin-defined settings panel. See [Plugin settings panel](#plugin-settings-panel) under Credentials. |
| `oauth` | object | No | OAuth2 Authorization Code flow config. See [OAuth](#9-oauth-integration). |
| `permissions` | object | No | Module-level permission whitelist for the RPC system. |
| `functions` | object | Yes | Maps function names to their metadata. This is the core of the manifest. |

### Functions Object

Each key in `functions` is a function name that must exist in `plugin.py`. The value is a metadata object:

```json
{
  "functions": {
    "my_function": {
      "label": "My Function",
      "description": "What this function does",
      "default_display": {
        "color": "#1DB954",
        "text": "Go",
        "image": "plugins/plugin/my_plugin/img/icon.png"
      },
      "display_states": {
        "default": { "image": "plugins/plugin/my_plugin/img/off.png" },
        "active":  { "image": "plugins/plugin/my_plugin/img/on.png" }
      },
      "ui": [ ... ]
    }
  }
}
```

| Field | Type | Required | Description |
|:---|:---|:---|:---|
| `label` | string | Yes | Human-readable name shown in the sidebar and editor. |
| `description` | string | No | Short description shown below the label. |
| `sidebar_icon` | string | No | Relative path to an image for the **sidebar** action tile only (same path style as `default_display.image`). Omitted or empty → generic “+” tile. **Not** derived from `default_display.image`; set explicitly when you want a tile graphic. Legacy alias: `action_tile_icon`. |
| `default_display` | object | No | Initial button appearance when dragged onto a slot. Supports `color` (hex), `text` (string), `image` (relative path), optional **`scroll_enabled`** / **`scroll_speed`** (title marquee), and all text-style fields: `show_title`, `text_position`, `text_size`, `text_bold`, `text_italic`, `text_underline`, `text_color`, `text_font`. Text-style fields declared here take the highest priority in the system/user/plugin merge chain. See [Text Style in default_display](#text-style-in-default_display) and [Text Style Priority Chain](#14-text-style-priority-chain). |
| `display_states` | object | No | Maps state keys (like `"default"`, `"active"`) to partial display overrides. Used for toggling button images. See [Display States](#6-display-states-and-toggling). |
| `poll` | object | No | Background display polling config. See [Display Polling](#7-display-polling). |
| `ui` | array | Yes | List of UI field definitions for the button editor. See [UI Field Types](#5-ui-field-types). Use `[]` for no fields. |
| `title_readonly` | boolean | No | When `true`, the web editor shows the title field as read-only with a **Read-only** badge. Use when the plugin or its poller owns the label (for example live clock text or transport state). The title is still persisted with the button like any other field; this flag is UI-only. |

### Permissions Object

Declares which standard library modules and functions the plugin uses. Used by the RPC permission system.

```json
{
  "permissions": {
    "webbrowser": ["open"],
    "subprocess": ["run"],
    "json": ["dumps", "loads"]
  }
}
```

Each key is a module name, and the value is a list of function/attribute names from that module.

---

## 4. plugin.py — Writing Functions

### Function Signature

Every function listed in the manifest must be a top-level callable in `plugin.py` with this signature:

```python
def function_name(config: Dict[str, Any]) -> Dict[str, Any]:
```

**Parameters:**
- `config` — A dict containing:
  - All values from the button's UI fields (keyed by their `id`)
  - All stored credentials for your plugin (merged in automatically)
  - Credentials are the base; per-button config values override them

**Returns:**
- A dict. Must include `"success": True` or `"success": False`.
- On failure, include an `"error"` string.
- Can include any additional keys you want (they're passed to the GUI).

### Minimal Example

```python
def greet(config: Dict[str, Any]) -> Dict[str, Any]:
    name = config.get("name") or "World"
    return {"success": True, "message": f"Hello, {name}!"}
```

### Error Handling Example

```python
def do_something(config: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # ... your logic ...
        return {"success": True, "action": "done"}
    except SomeError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {e}"}
```

### Importing Helper Modules

If your plugin has additional `.py` files, import them by adding the plugin directory to `sys.path`:

```python
import sys
from pathlib import Path

_PLUGIN_DIR = Path(__file__).parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from my_helper import MyClient  # noqa: E402
```

### Module-Level Caching

Plugin modules are cached in memory after first load. Module-level variables persist across button presses within one process. Use this for connection caching:

```python
_client_cache: dict = {}

def _get_client(config):
    key = config.get("api_key", "")
    if key not in _client_cache:
        _client_cache[key] = MyClient(key)
    return _client_cache[key]
```

### Config Dict Contents

When a button is pressed, the core builds the config dict by merging two sources:

```
config = {**credentials, **button_config}
```

1. **Credentials** — Values from `~/.config/pydeck/core/credentials.json` under your plugin's key (e.g. `client_id`, `client_secret`, `access_token`)
2. **Button config** — Values from the button's UI fields saved in `buttons.json`

Button config takes precedence, so users can override credentials per-button if needed.

---

## 5. UI Field Types

The `ui` array in each function definition controls what appears in the button editor panel. Each entry is a field object.

### Common Properties

Every field type supports these properties:

| Property | Type | Required | Description |
|:---|:---|:---|:---|
| `type` | string | Yes | One of: `input`, `number`, `checkbox`, `slider`, `select`, `radio` |
| `id` | string | Yes | Unique key within the function. This becomes the config key passed to your Python function. |
| `label` | string | Yes | Human-readable label shown above the field. |
| `default` | any | No | Default value when the button is first created. |
| `visible_if` | object | No | Conditionally show this field based on another field's value. |

### input — Text Input

A single-line text field.

```json
{
  "type": "input",
  "id": "url",
  "label": "URL",
  "placeholder": "https://example.com",
  "default": ""
}
```

| Property | Description |
|:---|:---|
| `placeholder` | Grayed-out hint text shown when the field is empty. |

### number — Numeric Input

A number field with optional min/max constraints.

```json
{
  "type": "number",
  "id": "volume_step",
  "label": "Volume Step (%)",
  "min": 1,
  "max": 100,
  "default": 10
}
```

| Property | Description |
|:---|:---|
| `min` | Minimum allowed value. |
| `max` | Maximum allowed value. |

### checkbox — Boolean Toggle

A checkbox that maps to `true`/`false`.

```json
{
  "type": "checkbox",
  "id": "auto_reconnect",
  "label": "Auto-reconnect on failure",
  "default": true
}
```

### slider — Range Slider

A horizontal slider.

```json
{
  "type": "slider",
  "id": "brightness",
  "label": "LED Brightness",
  "default": 50
}
```

### select — Dropdown

A dropdown menu with predefined options.

```json
{
  "type": "select",
  "id": "action",
  "label": "Action",
  "options": [
    { "label": "Play/Pause", "value": "play_pause" },
    { "label": "Next Track", "value": "next_track" },
    { "label": "Stop", "value": "stop" }
  ],
  "default": "play_pause"
}
```

Each option has:
- `label` — Title in the dropdown
- `value` — Value sent to your Python function via `config["action"]`

### radio — Radio Buttons

Mutually exclusive options rendered as radio buttons.

```json
{
  "type": "radio",
  "id": "mode",
  "label": "Mode",
  "options": [
    { "label": "Fast", "value": "fast" },
    { "label": "Normal", "value": "normal" },
    { "label": "Slow", "value": "slow" }
  ],
  "default": "normal"
}
```

### visible_if — Conditional Visibility

Show a field only when another field has a specific value. Add `visible_if` to any field:

```json
{
  "type": "number",
  "id": "step_percent",
  "label": "Volume Step (%)",
  "default": 5,
  "visible_if": {
    "field": "action",
    "value": "volume_up"
  }
}
```

This field only appears when the `action` field's value is `"volume_up"`. Works with all field types — the `field` references another field's `id` in the same function, and `value` is the string value to match against.

---

## 6. Display States and Toggling

Display states allow buttons to change their appearance based on plugin state (e.g. showing a different icon when muted vs unmuted).

### Defining Display States in the Manifest

Add a `display_states` object to a function definition. Each key is a state name, and the value is a partial display override:

```json
{
  "toggle_mute": {
    "label": "Mute",
    "default_display": {
      "image": "plugins/plugin/my_plugin/img/mute_off.png",
      "color": "#000000",
      "text": ""
    },
    "display_states": {
      "default": { "image": "plugins/plugin/my_plugin/img/mute_off.png" },
      "active":  { "image": "plugins/plugin/my_plugin/img/mute_on.png" }
    },
    "ui": []
  }
}
```

### Returning State from Python

To trigger a state change, return a `"state"` key from your function:

```python
def toggle_mute(config: Dict[str, Any]) -> Dict[str, Any]:
    # ... toggle logic ...
    is_muted = True  # result of toggle
    return {
        "success": True,
        "action": "mute",
        "muted": is_muted,
        "state": "active" if is_muted else "default",
    }
```

The core looks up `"active"` in `display_states`, finds `{"image": ".../mute_on.png"}`, and persists that to `buttons.json`. The button image updates on the Stream Deck and in the web GUI.

### display_update — Direct Override

Instead of named states, you can return a `display_update` dict directly:

```python
def set_color(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "success": True,
        "display_update": {
            "color": "#ff0000",
            "text": "RED",
        },
    }
```

This is useful for dynamic values that don't map to predefined states.

### related_states — Updating Sibling Buttons

When one button press should also update other buttons of the same plugin (e.g. pressing "deafen" should also show the "mute" button as active), return `related_states`:

```python
def toggle_deafen(config: Dict[str, Any]) -> Dict[str, Any]:
    # ... toggle logic ...
    return {
        "success": True,
        "state": "active" if is_deaf else "default",
        "related_states": {
            "toggle_mute": "active" if is_muted else "default",
        },
    }
```

The core finds all buttons in the current profile that use the same plugin and the `toggle_mute` function, then applies the `"active"` or `"default"` display_state to each of them. The pressed button itself is excluded from this lookup.

### Cross-Device Sync

When multiple Stream Decks are connected, pressing a button on one device automatically mirrors the resulting display state to matching buttons on all other devices — including both the pressed button's own state and all `related_states` updates.

**No opt-in required.** Any plugin that returns `state` and/or `related_states` gets this behavior automatically.

**Matching rule:** A button on Device B is a sync target when it uses the **same plugin name** and occupies the **same slot ID** as the updated button on Device A.

**What gets synced:**
- The pressed button's own `display_update` (resolved from `state`)
- All sibling updates generated by `related_states` (e.g. deafen → mute turns red)

**Latency:** Near-zero. After a press, the core writes the updated state to each other device's `buttons.json` and sends a `RELOAD` signal to that device's listener process, which pushes the change to hardware within one poll cycle (~16–20 ms).

**Example — Discord:** Pressing mute on Deck 1 causes Deck 2's mute button to turn red immediately. Pressing deafen causes both the deafen and mute buttons to turn red on all connected decks.

---

## 7. Display Polling

Display polling lets a button's appearance update automatically in the background — without the user pressing it. This is useful for live data like album art, system stats, clocks, or any state that changes over time.

### How It Works

1. A function in the manifest declares a `poll` block
2. The core runs a background thread that periodically calls the specified poll function
3. If the poll function returns a `display_update`, the button image is updated on the Stream Deck and in the web GUI via WebSocket

The polling system is fully generic — any plugin can use it. No changes to core files are needed.

### Declaring Polling in the Manifest

Add a `poll` object to any function definition in `manifest.json`:

```json
{
  "functions": {
    "play_pause": {
      "label": "Play / Pause",
      "poll": {
        "function": "poll_display",
        "interval_ms": 3000
      },
      "ui": []
    }
  }
}
```

| Field | Type | Required | Description |
|:---|:---|:---|:---|
| `function` | string | Yes | Name of the Python function in `plugin.py` to call for polling. Must be a top-level callable. |
| `interval_ms` | integer | No | Polling interval in milliseconds. Default: `3000`. Minimum: `1000`. |

The poll function is separate from the press function. Pressing the button calls `play_pause`, while the background poller calls `poll_display`. This keeps the toggle action separate from the display refresh.

### Writing a Poll Function

The poll function has the same signature as a regular plugin function — it receives the merged credentials + config dict. The key difference: it should **only return `display_update` when something actually changed**, to avoid unnecessary disk writes and WebSocket events.

```python
_last_known_state: str | None = None

def poll_display(config: Dict[str, Any]) -> Dict[str, Any]:
    """Called by the background poller. Returns display_update only on change."""
    try:
        current_state = fetch_current_state(config)
        global _last_known_state
        if current_state == _last_known_state:
            return {}  # No change — skip update
        _last_known_state = current_state
        return {
            "display_update": {
                "image": "plugins/plugin/my_plugin/img/latest.png"
            }
        }
    except Exception:
        return {}
```

**Rules for poll functions:**

- Return `{}` (empty dict) when nothing changed — the poller skips the update
- Return `{"display_update": {...}}` only when the display should change
- Change detection is the plugin's responsibility (track the last state yourself)
- Catch all exceptions — an error in a poll function must not crash the poller
- Keep it fast — the function runs on a shared background thread

### What the Poller Does

When a poll function returns a `display_update`:

1. **Runtime image state** is updated (so the next `/api/buttons/<id>/image` request renders the new image)
2. **buttons.json** is updated (so the change persists across restarts and the physical Stream Deck picks it up)
3. **A `display_update` WebSocket event** is emitted (so the web GUI refreshes the button image immediately)

### Preloading scheduled display updates (universal API)

Poll functions and **press** results may include **`preload_display_updates`**: a list of future `display_update` payloads the core applies **at specific times** without waiting for the next poll tick. This removes multi‑hundred‑millisecond jitter when you already know the next frames (for example a clock registering the next several second-boundary faces).

Return shape (alongside optional `display_update`):

```python
return {
    "display_update": { ... },  # optional: current frame, same as today
    "preload_display_updates": [
        {"apply_at": 1735689600.0, "display_update": {"text": "12:00:01", "text_size": 0}},
        {"apply_at": 1735689601.0, "display_update": {"text": "12:00:02", "text_size": 0}},
    ],
}
```

| Field | Type | Description |
|:---|:---|:---|
| `preload_display_updates` | array | Each element schedules one update. |
| `apply_at` | number | **UNIX timestamp in seconds** (float or int). When `time.time() >= apply_at`, the core applies that element’s `display_update` (same path as a normal poll: scroll registration, `buttons.json`, WebSocket, hardware via the listener). |
| `offset_ms` | integer | Alternative to `apply_at`: apply at `time.time() + offset_ms/1000` from when the core processed the result (useful for relative delays). |

**Rules:**

- New preloads **replace** any previous scheduled entries for the same `(device_id, button_id)` — always send a fresh chain when you emit preloads.
- The scheduler runs at ~50 ms resolution; use `apply_at` on clean second boundaries for wall clocks (`float(int(time.time()) + k)` pattern).
- Omit `preload_display_updates` if you do not need timed delivery; behavior stays unchanged.
- The same key is honored on **HTTP button press** responses (`plugin` result dict) so a manual refresh can re-seed the schedule.

The **clock** plugin uses this API to register the next several seconds ahead whenever the displayed second changes.

### Real Example — Spotify Album Art

The Spotify plugin uses polling to keep the play/pause button showing the current track's album cover:

**manifest.json:**

```json
{
  "play_pause": {
    "label": "Play / Pause",
    "poll": {
      "function": "poll_display",
      "interval_ms": 3000
    },
    "ui": [...]
  }
}
```

**plugin.py:**

```python
_last_art_url: str | None = None

def poll_display(config: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch current playback and return album art if the track changed."""
    try:
        client = _get_client(config)
        pb = client.get_playback()
        prev_url = _last_art_url
        art_path, _ = _fetch_album_art(pb)
        if art_path and _last_art_url != prev_url:
            return {"display_update": {"image": art_path}}
        return {}
    except Exception:
        return {}
```

The album art updates automatically every 3 seconds when the track changes. Pressing the button still toggles play/pause — the two behaviors are independent.

### Title marquee — `scroll_enabled` and `scroll_speed`

The core may **auto-scroll** long **`display.text`** labels horizontally when a line is wider than the visible title area (after trying smaller font sizes). Newlines (`\n`) split lines; the widest line controls fit and scroll — matching how Pillow draws multi-line labels.

| Key | Type | Default | Description |
|:---|:---|:---|:---|
| `scroll_enabled` | boolean | `true` | When `false`, the title never marquees: it stays centred with a static offset (font may still shrink). Set in `default_display` or `display_update`. A value stored on the button in `buttons.json` overrides the manifest default for that key. |
| `scroll_speed` | integer | (built-in minimum) | Pixels per tick when scrolling is active; larger is faster. The core clamps very small values up to a minimum while scrolling is enabled. |

**Example — clock with date on a second line, no marquee:**

```json
"default_display": {
  "text": "00:00",
  "text_position": "middle",
  "scroll_enabled": false
}
```

You can return `scroll_enabled` or `scroll_speed` from a poll function or press handler inside `display_update` like any other display field.

### Scrolling Text (scroll_text)

Plugins can set a **scrolling marquee label** on a button by including `scroll_text` in a `display_update`. This is useful for long strings that don't fit on the 80×80 button face — like song titles, status messages, or ticker data.

The scroll engine is built into the core and works with any plugin. No manifest declaration is needed — just return `scroll_text` from a poll function or button press.

**Behaviour:**

1. Text starts left-aligned (showing the beginning)
2. After a short pause it scrolls left so the rest of the text is revealed
3. Once the end is visible it pauses again, then scrolls back right to the start
4. Repeats indefinitely (ping-pong / bounce marquee)

If the text fits within the button without scrolling, it is rendered normally (centred).

**Returning scroll_text from a poll function:**

```python
def poll_display(config: Dict[str, Any]) -> Dict[str, Any]:
    title = get_current_title(config)
    if title:
        return {"display_update": {"scroll_text": title}}
    return {}
```

**Returning scroll_text from a button press:**

```python
def my_action(config: Dict[str, Any]) -> Dict[str, Any]:
    status = do_something(config)
    return {
        "success": True,
        "display_update": {
            "scroll_text": f"Status: {status}",
        },
    }
```

**Clearing scroll_text:**

Return an empty string to stop scrolling and revert to the static label:

```python
return {"display_update": {"scroll_text": ""}}
```

**Priority rules:**

- If the button's `display.text` field is non-empty (i.e. the user set a static label), the static label is always shown and `scroll_text` is ignored.
- `scroll_text` is runtime-only — it is **not** persisted to `buttons.json`. A server restart clears all active scrolls until the next poll cycle restores them.

**Combining with other display fields:**

`scroll_text` can be returned alongside `image`, `color`, or `text` in the same `display_update`:

```python
return {
    "display_update": {
        "image": "plugins/plugin/my_plugin/img/cover.jpg",
        "scroll_text": "Now Playing — Song Title",
    }
}
```

### Real Example — Spotify Album Art + Track Title

The Spotify plugin returns both album art and a scrolling track label:

**plugin.py:**

```python
_last_track_label: str | None = None

def _build_track_label(pb: dict | None) -> str:
    """Build a 'Title — Artist' string from playback data."""
    if not pb or not isinstance(pb, dict):
        return ""
    item = pb.get("item")
    if not isinstance(item, dict):
        return ""
    title = item.get("name", "")
    artists = item.get("artists", [])
    if isinstance(artists, list) and artists:
        names = [a.get("name", "") for a in artists if isinstance(a, dict)]
        artist_str = ", ".join(n for n in names if n)
        if artist_str:
            return f"{title} — {artist_str}"
    return title or ""


def poll_display(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return album art and track title when either changes."""
    global _last_track_label
    try:
        client = _get_client(config)
        pb = client.get_playback()
        display_update = {}

        art_path, _ = _fetch_album_art(pb)
        if art_path and _last_art_url != prev_url:
            display_update["image"] = art_path

        track_label = _build_track_label(pb)
        if track_label != _last_track_label:
            display_update["scroll_text"] = track_label or ""
            _last_track_label = track_label

        return {"display_update": display_update} if display_update else {}
    except Exception:
        return {}
```

The button shows the album cover as the background image with the track title scrolling across the bottom — "Bohemian Rhapsody — Queen" scrolls left then right in a loop.

---

## 8. Credentials

Plugins that interact with external APIs typically need secrets — API keys, client IDs, OAuth tokens, etc.  PyDeck stores these separately from button configuration so they can be shared across all buttons of the same plugin, edited in one place, and kept out of the buttons.json file.

### Where Credentials Are Stored

All credentials live in a single file:

```
~/.config/pydeck/core/credentials.json
```

This file is a flat JSON object. Each top-level key is a **plugin name** (matching the folder name under `plugins/plugin/`), and its value is an object of key–value pairs:

```json
{
  "spotify": {
    "client_id": "abc123def456",
    "client_secret": "secret789",
    "access_token": "BQD...long_token...",
    "refresh_token": "AQB...long_token..."
  },
  "discord": {
    "client_id": "1234567890",
    "client_secret": "abcdefg"
  },
  "my_weather_plugin": {
    "api_key": "wk_live_abc123"
  }
}
```

The file is created automatically the first time a user saves credentials through the GUI. If the file doesn't exist yet, the core treats every plugin as having an empty credential set (`{}`).

> **Security note:** `credentials.json` stores secrets in plaintext on disk. It lives in the user's home directory under `.config/pydeck/`, which is not world-readable on most systems, but plugins should still encourage users to use app-specific or restricted-scope credentials where possible.

### Declaring Credentials in the Manifest

To tell PyDeck that your plugin needs credentials, add a `credentials` array to `manifest.json`. Each entry describes one input field that will appear under **Settings → API** in the web UI (open **Settings** from the deck header, then choose the **API** category):

```json
{
  "name": "my_weather_plugin",
  "credentials": [
    { "id": "api_key", "label": "API Key", "type": "password" }
  ],
  "functions": { ... }
}
```

A more complex example with multiple fields:

```json
{
  "credentials": [
    { "id": "client_id",     "label": "Client ID",     "type": "text" },
    { "id": "client_secret", "label": "Client Secret", "type": "password" },
    { "id": "webhook_url",   "label": "Webhook URL",   "type": "text" }
  ]
}
```

Each entry has these fields:

| Field | Type | Description |
|:---|:---|:---|
| `id` | string | The key stored in `credentials.json` and injected into your function's `config` dict. Must be unique within the plugin. |
| `label` | string | Human-readable label shown next to the input field under **Settings → API**. |
| `type` | string | `"text"` renders a normal visible input. `"password"` renders a masked input and the saved value is displayed as `••••••••` when re-opened. |

If a plugin has **no** `credentials` array (or it's empty), the plugin simply won't appear in the API credentials list — no section, no fields.

### The API credentials UI

On **Settings → API**, the UI calls `GET /api/credentials`, which scans every discovered plugin's manifest for `credentials` declarations. For each plugin that declares credentials:

1. A **section** is shown with the plugin name as a header
2. **Input fields** are rendered for each credential definition
3. Existing values are pre-filled (password fields show `••••••••` instead of the real value)
4. A **Save** button persists the values
5. If the plugin also has an `oauth` config, an **Authorize** button and status badge are shown

### Plugin settings panel

Plugins can add a **custom HTML panel** in the **Settings** overlay (gear on the deck; URL stays `/`) and group multiple plugins under one sidebar category.

1. Add a `settings` object to `manifest.json`:

```json
"settings": {
  "category": "Integrations",
  "category_id": "integrations",
  "order": 10
}
```

| Field | Required | Description |
|:---|:---|:---|
| `category` | Yes | Human-readable sidebar label. Plugins with the same resolved `category_id` share one category. |
| `category_id` | No | Stable id (`a-z`, `0-9`, `-`). If omitted, it is derived from `category` (lowercase, non-alphanumeric → `-`). |
| `order` | No | Sort order for your plugin within that category (integer; lower first). |

2. Optionally add `plugins/plugin/<your_plugin>/settings.html`. Static HTML only; no server-side templating.

3. The settings page calls `GET /api/settings/categories` to build the sidebar (built-in categories **Appearance**, **Text defaults**, and **API** are always listed first). For each plugin in a category, the UI loads:

```
GET /api/plugins/<plugin_name>/settings/panel
```

If `settings.html` is missing, the category still appears when `settings` is declared, and the user sees a short note for that plugin’s panel.

With Settings open, **Escape** closes the overlay and returns to the deck (URL remains `/`).

When the user clicks Save:
- The GUI sends `POST /api/credentials/<plugin_name>` with the field values
- The backend **merges** the new values into the existing entry — it never wipes the whole entry
- Values that are still `••••••••` (the mask) are **skipped**, so re-saving the form without editing a password field won't destroy the stored secret
- Any extra keys already in `credentials.json` (like `access_token` from OAuth) are preserved

### How Credentials Reach Your Function

When a button is pressed, the core performs a two-step merge before calling your function:

```
Step 1: Load credentials.json → read the object under your plugin's name
Step 2: Merge with button config → credentials first, then button config on top
```

In code (from `lib/button.py`):

```python
merged = {**credentials_from_file, **per_button_config}
fn(merged)
```

This means:
- **Credentials are the base layer** — every function call automatically gets `client_id`, `api_key`, `access_token`, etc. without the user configuring each button individually.
- **Per-button config overrides credentials** — if a user sets `api_key` in a button's form fields, that value takes precedence over the one in `credentials.json`. This allows advanced users to use different keys per button.

Your function receives the merged result as a single `config` dict:

```python
def get_weather(config: Dict[str, Any]) -> Dict[str, Any]:
    api_key = config.get("api_key", "")
    city = config.get("city", "London")

    # api_key comes from credentials.json automatically
    # city comes from the button's per-button UI config
    ...
```

### Credential Lifecycle Example

Here's the full lifecycle of how a credential value flows through the system, using a weather plugin as an example:

**1. Plugin declares the credential:**

```json
{
  "name": "weather",
  "credentials": [
    { "id": "api_key", "label": "OpenWeather API Key", "type": "password" }
  ],
  "functions": {
    "current": {
      "label": "Current Weather",
      "ui": [
        { "type": "input", "id": "city", "label": "City", "default": "London" }
      ]
    }
  }
}
```

**2. User enters the key under Settings → API:**

The GUI shows a password input labeled "OpenWeather API Key". The user pastes their key and clicks Save.

**3. The key is persisted to disk:**

```json
// ~/.config/pydeck/core/credentials.json
{
  "weather": {
    "api_key": "wk_live_abc123def456"
  }
}
```

**4. User assigns the function to a button:**

They drag "weather / current" onto button slot 0 and set the city to "Berlin".

**5. The button config is saved (no credential data here):**

```json
// In the active profile's buttons.json
{
  "id": 0,
  "type": "plugin",
  "plugin": "weather",
  "function": "current",
  "config": { "city": "Berlin" },
  "display": { "text": "Weather", "color": "#4a90d9" }
}
```

**6. User presses the button — core merges and calls the function:**

```python
# What the core does internally:
credentials = {"api_key": "wk_live_abc123def456"}  # from credentials.json
button_config = {"city": "Berlin"}                   # from buttons.json
merged = {**credentials, **button_config}
# merged = {"api_key": "wk_live_abc123def456", "city": "Berlin"}

result = weather_plugin.current(merged)
```

**7. Your function receives the merged config:**

```python
def current(config):
    api_key = config["api_key"]   # "wk_live_abc123def456"
    city = config["city"]         # "Berlin"
    # Make API call...
```

### OAuth Tokens in Credentials

When a plugin uses [OAuth](#9-oauth-integration), the token exchange automatically writes `access_token` and `refresh_token` into the same `credentials.json` entry alongside the `client_id` and `client_secret`:

```json
{
  "spotify": {
    "client_id": "abc123",
    "client_secret": "secret456",
    "access_token": "BQD...",
    "refresh_token": "AQB..."
  }
}
```

These tokens are then merged into `config` on every button press, so your plugin function can use `config["access_token"]` directly. When your plugin refreshes an expired token, it should write the new token back to `credentials.json` so it persists across restarts. See the Spotify plugin's `_save_tokens()` method for an example.

### Multiple Buttons, One Credential Set

A key design principle: credentials are per-plugin, not per-button. If you have five Spotify buttons (play, pause, next, previous, volume), they all share the same `client_id`, `client_secret`, `access_token`, and `refresh_token` from a single entry in `credentials.json`. The user only has to configure credentials once.

### Credential Validation in Your Function

Always check that required credentials are present before using them. If a credential is missing, return a clear error message pointing the user to **Settings → API**:

```python
def my_function(config):
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        return {
            "success": False,
            "error": "API key not configured — add it under Settings → API",
        }
    # Safe to proceed...
```

This is important because:
- A fresh install won't have any credentials yet
- The user might have forgotten to save credentials before testing
- OAuth tokens can expire or be revoked

---

## 9. OAuth Integration

Plugins that need OAuth2 Authorization Code flow can declare their OAuth config in the manifest. The core handles the entire browser-based flow generically.

### Declaring OAuth in the Manifest

Replace a simple `"oauth": true` with an object:

```json
{
  "oauth": {
    "authorize_url": "https://accounts.spotify.com/authorize",
    "token_url": "https://accounts.spotify.com/api/token",
    "scopes": "user-read-playback-state user-modify-playback-state",
    "auth_method": "basic"
  }
}
```

| Field | Type | Required | Description |
|:---|:---|:---|:---|
| `authorize_url` | string | Yes | The provider's authorization endpoint URL. |
| `token_url` | string | Yes | The provider's token exchange endpoint URL. |
| `scopes` | string | No | Space-separated OAuth scopes to request. |
| `auth_method` | string | No | How client credentials are sent to the token endpoint. `"basic"` (default) sends Base64-encoded `client_id:client_secret` in the Authorization header. `"post"` sends them as form body fields. |

### How the OAuth Flow Works

1. User saves `client_id` and `client_secret` under **Settings → API**
2. User clicks **Authorize** in the same place
3. The GUI calls `GET /api/<plugin_name>/authorize`
4. The core reads the manifest's `oauth` config and builds the authorization URL
5. The browser opens the provider's auth page
6. After the user approves, the provider redirects to `http://127.0.0.1:8686/oauth/<plugin_name>/callback`
7. The core exchanges the authorization code for tokens
8. `access_token` and `refresh_token` are saved to `credentials.json` under the plugin's key
9. Tokens are automatically included in `config` on every button press

### Setting Up the Provider

When creating your app on the OAuth provider's dashboard, set the redirect URI to:

```
http://127.0.0.1:8686/oauth/<your_plugin_name>/callback
```

For example, a Spotify plugin would use:

```
http://127.0.0.1:8686/oauth/spotify/callback
```

### Token Refresh

The core handles the initial token exchange and storage. Your plugin is responsible for refreshing expired tokens using the `refresh_token` from `config`. See the Spotify plugin's `SpotifyClient._req()` method for an example that auto-refreshes on 401 responses.

---

## 10. Custom CSS — style.css

Each plugin can provide its own CSS by placing a `style.css` file in the plugin folder. The core automatically scans all plugins and serves their CSS combined at `/api/plugins/styles.css`.

### How It Works

1. Place `style.css` in your plugin folder: `plugins/plugin/my_plugin/style.css`
2. The route `GET /api/plugins/styles.css` scans every `plugins/plugin/*/` directory for `style.css`
3. All found CSS files are concatenated and served as one stylesheet
4. The HTML template includes `<link rel="stylesheet" href="/api/plugins/styles.css">` after the core stylesheet
5. Plugin CSS loads after the core CSS, so plugin rules can override core styles

No registration, no config — just drop the file and it's picked up.

### What to Put in style.css

Plugin-specific theme colors and UI component styles. The core uses CSS classes based on the plugin name via `data-action-type` attributes. Common patterns:

```css
/* Sidebar tile icon color */
.action-tile[data-action-type="my_plugin"] .action-tile-icon {
    background: rgba(100, 200, 150, 0.18);
    color: #64c896;
}

/* Properties panel badge color */
.action-badge.badge-my_plugin {
    background: rgba(100, 200, 150, 0.18);
    color: #64c896;
}

/* Settings → API (credentials) UI */
.api-section-icon.my_plugin-icon {
    background: rgba(100, 200, 150, 0.18);
    color: #64c896;
}

/* Event log tag color */
.log-tag-my_plugin {
    background: #122e1e;
    color: #64c896;
}
```

### Real Example — Spotify's style.css

```css
/* Spotify plugin theme */
.action-tile[data-action-type="spotify"] .action-tile-icon {
    background: rgba(29,185,84,0.18);
    color: #1DB954;
}
.action-badge.badge-spotify {
    background: rgba(29,185,84,0.18);
    color: #1DB954;
}
.api-section-icon.spotify-icon {
    background: rgba(29,185,84,0.18);
    color: #1DB954;
}
.log-tag-spotify {
    background: #122212;
    color: #1DB954;
}
```

---

## 11. Client-Side Popup API — PyDeck.popup

PyDeck exposes a global `window.PyDeck` object with promise-based popup functions. These replace the browser's native `confirm()` and `prompt()` dialogs with themed modals that match the PyDeck dark UI.

Plugins can call these from any inline `onclick` handler or injected script within their `style.css` / form HTML.

### PyDeck.confirm(message, opts?)

Show a confirmation dialog. Returns `Promise<boolean>` — `true` if confirmed, `false` / `undefined` if cancelled.

```js
const ok = await PyDeck.confirm('Delete this item?', {
    title: 'Delete',          // dialog title (default: "Confirm")
    confirmText: 'Delete',    // confirm button label (default: "Confirm")
    cancelText: 'Cancel',     // cancel button label (default: "Cancel")
    danger: true,             // styles the confirm button red (default: false)
});
if (ok) { /* proceed */ }
```

### PyDeck.prompt(message, opts?)

Show a text input dialog. Returns `Promise<string|null>` — the trimmed input value, or `null` if cancelled/empty.

```js
const name = await PyDeck.prompt('Enter a name:', {
    title: 'New Item',        // dialog title (default: "Input")
    placeholder: 'My item',   // input placeholder text
    defaultValue: '',          // pre-filled input value
    confirmText: 'Create',    // confirm button label (default: "OK")
    cancelText: 'Cancel',     // cancel button label (default: "Cancel")
});
if (name) { /* use name */ }
```

### PyDeck.popup(config)

Low-level fully customizable popup. Returns `Promise<any>` that resolves with the clicked button's `value`.

```js
const choice = await PyDeck.popup({
    title: 'Choose an action',
    body: '<p>What would you like to do?</p>',   // HTML string
    buttons: [
        { label: 'Cancel', value: null,     style: 'secondary' },
        { label: 'Save',   value: 'save',   style: 'primary' },
        { label: 'Delete', value: 'delete', style: 'danger' },
    ],
});
```

Button `style` options: `"primary"` (accent blue), `"danger"` (red), `"secondary"` (default grey).

Pressing **Escape** closes the popup and resolves with `undefined`.

---

## 12. Plugin Images — img/

Place image files in `plugins/plugin/my_plugin/img/`. They are served by the core at:

```
GET /api/plugins/<plugin_name>/img/<filename>
```

Supported formats: `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`

### Using Images in default_display

Reference images using their relative path from the project root:

```json
{
  "default_display": {
    "image": "plugins/plugin/my_plugin/img/icon.png",
    "color": "#000000",
    "text": ""
  }
}
```

<a name="text-style-in-default_display"></a>
### Text Style in default_display

Plugins can declare any of the text-style fields inside `default_display`. These values sit at the **highest priority** in the three-layer style merge chain, overriding both the user's per-button settings and the system defaults.

| Field | Type | Default | Description |
|:---|:---|:---|:---|
| `show_title` | boolean | `true` | Whether the button label is rendered at all. |
| `text_position` | string | `"bottom"` | Vertical position of the text: `"top"`, `"middle"`, or `"bottom"`. |
| `text_size` | integer | `0` | Font size in pixels. `0` = auto (fits the label to the button). |
| `text_bold` | boolean | `false` | Render the label in bold. |
| `text_italic` | boolean | `false` | Render the label in italic. |
| `text_underline` | boolean | `false` | Draw an underline beneath the label. |
| `text_color` | string | `""` | Hex color for the label (e.g. `"#ffffff"`). `""` = auto-contrasting. |
| `text_font` | string | `""` | Font family name (must be installed on the host system). `""` = DejaVu Sans. |

**Example** — a Spotify button that places the track name in the middle in white, using a specific font:

```json
"default_display": {
  "color": "#1DB954",
  "text": "",
  "image": "plugins/plugin/spotify/img/icon.png",
  "text_position": "middle",
  "text_size": 11,
  "text_bold": false,
  "text_italic": false,
  "text_underline": false,
  "text_color": "#ffffff",
  "text_font": "Noto Sans"
}
```

Only the fields you declare are applied at plugin priority; any omitted field falls through to the user's per-button setting or the system default.

### Using Images in display_states

```json
{
  "display_states": {
    "default": { "image": "plugins/plugin/my_plugin/img/off.png" },
    "active":  { "image": "plugins/plugin/my_plugin/img/on.png" }
  }
}
```

### Icon Gallery

All plugin images are automatically discovered and shown in the Icon Gallery (the image picker in the button editor). Users can browse and select any plugin's icons for any button.

The **sidebar** library tile uses only `sidebar_icon` (see functions table), not `default_display.image`.

---

## 13. options.json (Marketplace Metadata)

Optional file for future plugin marketplace/catalog features. Not used by the core runtime.

```json
{
  "name": "My Plugin",
  "description": "A longer description of what the plugin does",
  "features": [
    "Feature one",
    "Feature two"
  ],
  "options": {
    "client_id": "",
    "client_secret": ""
  },
  "metadata": {
    "category": "media",
    "tags": ["music", "playback", "media"]
  }
}
```

---

## 14. Button Types

PyDeck supports three button types. Plugins use `plugin` and `plugin_loop`.

### plugin — Single Press

The standard button type. Calls one plugin function on each press.

```json
{
  "id": 0,
  "type": "plugin",
  "plugin": "spotify",
  "function": "play_pause",
  "config": {},
  "display": {
    "color": "#1DB954",
    "text": "Play",
    "image": null
  }
}
```

### plugin_loop — Repeating Press

Calls the function repeatedly at a fixed interval. Used for live-updating displays (e.g. a clock, system monitor).

```json
{
  "id": 1,
  "type": "plugin_loop",
  "plugin": "clock",
  "function": "update_time",
  "interval_ms": 1000,
  "config": {},
  "display": {
    "color": "#333333",
    "text": "00:00"
  }
}
```

| Field | Description |
|:---|:---|
| `interval_ms` | Positive integer. How often (in milliseconds) the function is called. |

### action — Multi-Step Sequence

Runs a named sequence of plugin calls and delays defined in `actions.json`. See [Actions](#15-actions-multi-step-sequences).

```json
{
  "id": 2,
  "type": "action",
  "action": "mute_then_deafen",
  "config": {},
  "display": {
    "color": "#ff6600",
    "text": "Macro"
  }
}
```

---

## 15. Actions (Multi-Step Sequences)

Actions are named sequences of plugin calls and delays, defined in `~/.config/pydeck/core/actions.json`. They allow a single button press to trigger multiple plugin functions in order.

### actions.json Format

```json
{
  "actions": {
    "mute_then_deafen": [
      { "plugin": "discord", "function": "toggle_mute" },
      { "delay": 2000 },
      { "plugin": "discord", "function": "toggle_deafen" }
    ],
    "launch_and_play": [
      { "plugin": "browser", "function": "open_url" },
      { "delay": 3000 },
      { "plugin": "spotify", "function": "play_pause" }
    ]
  }
}
```

Each step is either:
- **Plugin call**: `{ "plugin": "<name>", "function": "<func>" }` — runs the function
- **Delay**: `{ "delay": <milliseconds> }` — pauses before the next step

### Action Button Toggling

Action buttons support a toggle feature via config fields:

| Config Key | Description |
|:---|:---|
| `action_switch_enabled` | Set to `true` to enable toggle behavior. |
| `action_next` | Name of the action to switch to after this press. |
| `action_switch_toggle_image` | Set to `true` to also swap button images. |
| `action_image_primary` | Image path for the primary state. |
| `action_image_secondary` | Image path for the secondary state. |

On each press, the button swaps its `action` and `action_next` values, effectively toggling between two actions.

---

## 16. REST API Reference

All endpoints are served by `start.py` on port **8686**.

### Plugin Discovery

#### `GET /api/plugins`

Returns all discovered plugins with their functions.

**Response:**

```json
{
  "plugins": [
    {
      "name": "spotify",
      "description": "Control Spotify playback via the Web API",
      "functions": {
        "play_pause": {
          "label": "Play / Pause",
          "description": "Toggle Spotify play/pause",
          "default_display": { "color": "#1DB954", "text": "Play" }
        }
      }
    }
  ]
}
```

#### `GET /api/plugins/<name>/functions/<func_name>/form`

Returns the HTML form fragment for one plugin function's UI fields.

**Response:** Raw HTML (`text/html`) for the editor panel.

#### `GET /api/settings/categories`

Returns sidebar categories for the Settings overlay (same document as the deck): built-in **Appearance**, **Text defaults**, and **API**, plus any categories declared by plugins via the manifest `settings` object.

**Response:**

```json
{
  "categories": [
    { "id": "appearance", "label": "Appearance", "builtin": true, "plugins": [] },
    { "id": "integrations", "label": "Integrations", "builtin": false, "plugins": [{ "name": "my_plugin", "order": 0 }] }
  ]
}
```

#### `GET /api/plugins/<name>/settings/panel`

Returns `plugins/plugin/<name>/settings.html` if it exists.

**Response:** Raw HTML (`text/html`), or **404** if the file is missing.

#### `GET /api/plugins/<name>/img/<filename>`

Serves a static image from a plugin's `img/` directory.

#### `GET /api/plugins/styles.css`

Serves all plugin `style.css` files concatenated into one stylesheet.

#### `GET /api/plugins/<name>/api/<path:endpoint>`

Generic plugin data API. Any plugin can expose a data function by defining `api_<endpoint>(config)` as a top-level callable in `plugin.py`. It is then reachable at this URL with the plugin's stored credentials merged into `config` automatically.

**Example — a plugin that exposes an `api_entities` function:**

```python
# plugin.py
def api_entities(config: Dict[str, Any]) -> list:
    client = _get_client(config)
    return client.list_entities()
```

This function becomes available at `GET /api/plugins/my_plugin/api/entities`.

**Response:** Whatever the `api_<endpoint>` function returns, serialized as JSON.

This is the mechanism used by the `api_select` UI field type to populate dynamic dropdowns (e.g. the Home Assistant entity picker).

### Icons

#### `GET /api/icons`

Returns metadata for all discovered plugin icons.

**Response:**

```json
{
  "icons": [
    {
      "plugin": "discord",
      "name": "mute_0",
      "filename": "mute_0.png",
      "url": "/api/plugins/discord/img/mute_0.png",
      "rel": "plugins/plugin/discord/img/mute_0.png"
    }
  ]
}
```

### Buttons

#### `GET /api/buttons`

Returns all buttons in the active profile.

**Response:**

```json
{
  "buttons": [
    {
      "id": 0,
      "type": "plugin",
      "plugin": "spotify",
      "function": "play_pause",
      "config": {},
      "display": { "color": "#1DB954", "text": "Play", "image": null }
    }
  ]
}
```

#### `POST /api/buttons/<id>`

Create or update a button. Send the full button object as JSON.

**Request body:**

```json
{
  "id": 0,
  "type": "plugin",
  "plugin": "browser",
  "function": "open_url",
  "config": { "url": "https://youtube.com" },
  "display": { "color": "#ff0000", "text": "YT", "image": null }
}
```

**Response:** The normalized button object.

#### `DELETE /api/buttons/<id>`

Delete a button by ID.

**Response:** The removed button object.

#### `GET /api/buttons/<slot>/image`

Render the button at the given slot as a PNG image. Returns `image/png`.

#### `POST /api/buttons/<id>/press`

Execute a button press from the web UI and return the result.

**Response:**

```json
{
  "id": 0,
  "type": "plugin",
  "plugin": "spotify",
  "function": "play_pause",
  "result": {
    "success": true,
    "action": "play",
    "is_playing": true
  }
}
```

### Actions

#### `GET /api/actions`

Returns all configured action names.

**Response:**

```json
{
  "actions": ["mute_then_deafen", "launch_and_play"]
}
```

### Credentials

#### `GET /api/credentials`

Returns all plugins that declare credentials, with masked password values.

**Response:**

```json
{
  "credentials": {
    "spotify": {
      "credentials": [
        { "id": "client_id", "label": "Client ID", "type": "text" },
        { "id": "client_secret", "label": "Client Secret", "type": "password" }
      ],
      "values": {
        "client_id": "abc123",
        "client_secret": "••••••••"
      },
      "oauth": true,
      "authorized": true
    }
  }
}
```

#### `POST /api/credentials/<plugin_name>`

Save credentials for a plugin. Masked values (`••••••••`) are skipped to avoid overwriting.

**Request body:**

```json
{
  "client_id": "new_id",
  "client_secret": "new_secret"
}
```

### OAuth

#### `GET /api/<plugin_name>/authorize`

Returns the OAuth authorization URL for a plugin. The GUI opens this URL in a new browser tab.

**Response:**

```json
{
  "url": "https://accounts.spotify.com/authorize?client_id=...&redirect_uri=..."
}
```

#### `GET /oauth/<plugin_name>/callback`

Handles the OAuth redirect from the provider. Exchanges the authorization code for tokens and saves them to `credentials.json`. Returns a simple HTML page telling the user they can close the tab.

### Folders

#### `POST /api/folders/<folder_id>`

Create a folder entry if it doesn't exist. Automatically adds a "back" button at the last slot.

**Request body (optional):**

```json
{ "name": "Gaming" }
```

#### `DELETE /api/folders/<folder_id>`

Remove a folder entry.

### Settings

#### `GET /api/status`

Returns server status and current brightness.

**Response:**

```json
{ "status": "ok", "brightness": 70 }
```

#### `POST /api/brightness`

Set the Stream Deck brightness.

**Request body:**

```json
{ "value": 85 }
```

---

## 17. WebSocket Events

The server uses Socket.IO to push real-time events to the web GUI. Connect to the same host/port as the HTTP server.

### Event: `deck_event`

All events are emitted under the `deck_event` channel with a `type` field:

| Type | Fields | Description |
|:---|:---|:---|
| `press` | `button`, `device_id`, `result?` | A button was pressed (physical or web). `result` contains the plugin return dict. |
| `error` | `button`, `device_id`, `error` | A button press failed. `error` is the error message string. |
| `display_update` | `button`, `device_id` | A button's display was updated (by poller or cross-device sync). GUI should refresh that button's image. |
| `folder_change` | `device_id` | The active folder changed. GUI should reload all button images. |

All events include a `device_id` field so the GUI can scope updates to the correct device. Cross-device sync emits `display_update` events for **all** affected devices simultaneously — a client viewing Device B will see its buttons update live when Device A is pressed.

---

## 18. Config and File Paths

### Directory Layout

```
~/.config/pydeck/
└── core/
    ├── config.json            # Active profile name and global settings
    ├── credentials.json       # Plugin credentials (client IDs, tokens, etc.)
    ├── folders.json           # Folder definitions for virtual pages
    ├── actions.json           # Named multi-step action sequences
    └── profiles/
        ├── main/
        │   └── buttons.json   # Button definitions for the "main" profile
        └── gaming/
            └── buttons.json   # Button definitions for the "gaming" profile
```

### config.json

```json
{
  "buttonProfiles": "main"
}
```

The `buttonProfiles` value selects which profile's `buttons.json` is active.

### buttons.json

```json
{
  "buttons": [
    {
      "id": 0,
      "type": "plugin",
      "plugin": "spotify",
      "function": "play_pause",
      "config": {},
      "display": { "color": "#1DB954", "text": "Play", "image": null }
    }
  ]
}
```

Buttons are sorted by `id`. The Stream Deck listener maps buttons to physical slots in sorted order.

---

## 19. Real-World Plugin Examples

### Browser — Minimal Plugin (No Credentials)

The simplest possible plugin. Opens URLs in the default browser.

**Directory:**

```
plugins/plugin/browser/
├── manifest.json
└── plugin.py
```

**manifest.json:**

```json
{
  "name": "browser",
  "version": "1.0.0",
  "description": "Open URLs in the default browser",
  "permissions": {
    "webbrowser": ["open"]
  },
  "functions": {
    "open_url": {
      "label": "Open URL",
      "description": "Launch a custom URL in your default browser",
      "ui": [
        {
          "type": "input",
          "id": "url",
          "label": "URL",
          "default": "https://youtube.com"
        }
      ]
    }
  }
}
```

**plugin.py:**

```python
import webbrowser
from typing import Any, Dict

def open_url(config: Dict[str, Any]) -> Dict[str, Any]:
    url = str(config.get("url") or "https://youtube.com")
    opened = webbrowser.open(url, new=2)
    return {
        "success": bool(opened),
        "url": url,
        "message": "Browser launch attempted",
    }
```

**Takeaway:** No credentials, no images, no CSS. Just a manifest and a Python file.

---

### Media Control — Multiple Functions with Shared Logic

Controls system media playback. Shows how to use `select` dropdowns and `visible_if` conditional fields.

**Key manifest pattern — a "mega function" using select + visible_if:**

```json
{
  "media_control": {
    "label": "Media Control",
    "description": "Run a media command",
    "ui": [
      {
        "type": "select",
        "id": "action",
        "label": "Action",
        "options": [
          { "label": "Play/Pause", "value": "play_pause" },
          { "label": "Volume Up", "value": "volume_up" },
          { "label": "Volume Down", "value": "volume_down" }
        ],
        "default": "play_pause"
      },
      {
        "type": "input",
        "id": "player",
        "label": "Player Filter (optional)",
        "placeholder": "spotify",
        "default": ""
      },
      {
        "type": "number",
        "id": "step_percent",
        "label": "Volume Step (%)",
        "default": 5
      }
    ]
  }
}
```

**plugin.py pattern — dispatching by action:**

```python
def media_control(config: Dict[str, Any]) -> Dict[str, Any]:
    action = config.get("action", "play_pause")
    player = config.get("player", "")

    if action in ("volume_up", "volume_down"):
        step = int(config.get("step_percent") or 5)
        return _adjust_volume(action, step)
    else:
        return _playerctl_action(action, player)
```

**Takeaway:** One function can handle many actions via a select dropdown. Use `visible_if` to show fields only when relevant.

---

### Folder — Plugin That Modifies Button State

The folder plugin swaps all deck buttons when "entering" a folder and restores them when "returning". Shows how plugins can directly modify `buttons.json`.

**Key return pattern — signaling a folder change:**

```python
def enter_folder(config: Dict[str, Any]) -> Dict[str, Any]:
    # ... swap buttons.json with folder contents ...
    return {
        "success": True,
        "folder_id": folder_id,
        "folder_change": True,  # tells the listener to reload
    }
```

**Takeaway:** Plugins can read/write PyDeck config files directly. The `folder_change` key triggers a full GUI reload.

---

### Discord — Display States and Related States

Toggles Discord mute/deafen with image-based state tracking. Shows `display_states` and `related_states`.

**manifest.json — display_states:**

```json
{
  "toggle_mute": {
    "label": "Discord Mute",
    "default_display": {
      "image": "plugins/plugin/discord/img/mute_0.png",
      "color": "#000000",
      "text": ""
    },
    "display_states": {
      "default": { "image": "plugins/plugin/discord/img/mute_0.png" },
      "active":  { "image": "plugins/plugin/discord/img/mute_1.png" }
    },
    "ui": []
  }
}
```

**plugin.py — returning state + related_states:**

```python
def toggle_mute(config: Dict[str, Any]) -> Dict[str, Any]:
    rpc = _get_rpc(config.get("client_id"), config.get("client_secret"))
    state = rpc.toggle_mute()
    return {
        "success": True,
        "action": "mute",
        "muted": state["mute"],
        "deafened": state["deaf"],
        "state": "active" if state["mute"] else "default",
        "related_states": {
            "toggle_deafen": "active" if state["deaf"] else "default",
        },
    }
```

When mute is toggled, the deafen button's display also updates to reflect the current deaf state.

**Takeaway:** Use `display_states` for image toggling. Use `related_states` to keep sibling buttons in sync.

---

### Spotify — OAuth + API Client + Token Refresh

The most complex plugin. Uses OAuth for authorization, a dedicated API client module, and module-level caching.

**Directory:**

```
plugins/plugin/spotify/
├── manifest.json
├── plugin.py
├── spotify_client.py
├── options.json
└── style.css
```

**manifest.json — OAuth config:**

```json
{
  "oauth": {
    "authorize_url": "https://accounts.spotify.com/authorize",
    "token_url": "https://accounts.spotify.com/api/token",
    "scopes": "user-read-playback-state user-modify-playback-state user-read-currently-playing",
    "auth_method": "basic"
  },
  "credentials": [
    { "id": "client_id",     "label": "Client ID",     "type": "text" },
    { "id": "client_secret", "label": "Client Secret", "type": "password" }
  ]
}
```

**plugin.py — client caching pattern:**

```python
_client_cache: dict[tuple[str, str], SpotifyClient] = {}

def _get_client(config: Dict[str, Any]) -> SpotifyClient:
    cid = str(config.get("client_id") or "").strip()
    csec = str(config.get("client_secret") or "").strip()
    if not cid or not csec:
        raise SpotifyError("client_id and client_secret are required")

    key = (cid, csec)
    client = _client_cache.get(key)
    if client is None:
        client = SpotifyClient(
            cid, csec,
            access_token=str(config.get("access_token") or ""),
            refresh_token=str(config.get("refresh_token") or ""),
        )
        _client_cache[key] = client
    return client


def play_pause(config: Dict[str, Any]) -> Dict[str, Any]:
    try:
        client = _get_client(config)
        pb = client.get_playback()
        if pb and pb.get("is_playing"):
            client.pause()
            return {"success": True, "action": "pause", "is_playing": False}
        else:
            client.play()
            return {"success": True, "action": "play", "is_playing": True}
    except SpotifyError as e:
        return {"success": False, "error": str(e)}
```

**spotify_client.py — auto token refresh:**

```python
def _req(self, method, path, query=None, body=None, _retry=True):
    # ... make API request ...
    try:
        # ... urllib request ...
    except urllib.error.HTTPError as e:
        if e.code == 401 and _retry:
            if self.refresh():
                return self._req(method, path, query, body, _retry=False)
        raise SpotifyError(msg)
```

**Takeaway:** OAuth tokens flow automatically via `config`. Cache clients at module level. Handle token refresh in your API client.

---

## 20. Tips and Best Practices

### Plugin Independence

Plugins must be fully self-contained. All functionality lives in the plugin folder:
- No modifications to `start.py`, `lib/`, or `app/` files
- CSS goes in `style.css`, not in the core stylesheet
- Images go in `img/`, served via the generic image route
- OAuth config goes in the manifest, handled by the generic OAuth routes

### Return Format

Always return a dict with `"success": True/False`:

```python
# Good
return {"success": True, "data": result}
return {"success": False, "error": "Something went wrong"}

# Bad — missing success flag
return {"data": result}
return result_string
```

### Error Handling

Catch exceptions in your function and return them as error dicts. If your function raises an uncaught exception, the core wraps it in a `RuntimeError` and the button shows an error in the GUI.

```python
def my_function(config):
    try:
        return {"success": True}
    except MySpecificError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Unexpected: {e}"}
```

### Cache Eviction

If cached state becomes stale (e.g. credentials changed, connection dropped), evict the cache entry so the next press creates a fresh instance:

```python
def _evict_client(config):
    key = (config.get("client_id", ""), config.get("client_secret", ""))
    _client_cache.pop(key, None)

def my_function(config):
    try:
        client = _get_client(config)
        return client.do_thing()
    except ConnectionError as e:
        _evict_client(config)
        return {"success": False, "error": str(e)}
```

### File Organization

For complex plugins with multiple modules:

```
plugins/plugin/my_plugin/
├── manifest.json
├── plugin.py          # Entry point — thin wrappers that call into your client
├── my_client.py       # API client / business logic
├── style.css          # Theme colors
├── options.json       # Marketplace metadata
└── img/
    ├── icon.png
    ├── state_on.png
    └── state_off.png
```

Keep `plugin.py` as a thin orchestration layer. Put complex logic in separate modules.

---

## 14. Text Style Priority Chain

PyDeck resolves the final text style for every rendered button through a three-layer merge. Lower layers provide fallback values; higher layers win for any field they explicitly set.

```
┌─────────────────────────────────────────────────────────────────┐
│  Priority (highest → lowest)                                    │
│                                                                 │
│  3. Plugin manifest  default_display  ← always wins            │
│  2. User per-button  display settings ← wins over system       │
│  1. System Default   (Settings UI)    ← global fallback        │
└─────────────────────────────────────────────────────────────────┘
```

### Layer 1 — System Default

The **System Default** is a global fallback that applies to every button that has no per-button override. It is configured in the PyDeck web UI under **Settings → Text defaults** (open Settings from the deck header).

The defaults are stored in `~/.config/pydeck/core/config.json` under the key `text_style_defaults` and can also be read/written via the API:

```
GET  /api/settings/text-style   → current system default values
POST /api/settings/text-style   → update (partial or full)
```

**Default values** (when no system default has been saved):

| Field | Value |
|:---|:---|
| `show_title` | `true` |
| `text_position` | `"bottom"` |
| `text_size` | `0` (auto) |
| `text_bold` | `false` |
| `text_italic` | `false` |
| `text_underline` | `false` |
| `text_color` | `""` (auto-contrasting) |
| `text_font` | `""` (DejaVu Sans) |

### Layer 2 — User Per-Button Settings

The user can customise text style for each individual button through the **Title → T↓** popup in the button editor. These settings are saved in the button's `display` object inside `buttons.json`. They override the system default for that button.

### Layer 3 — Plugin Manifest (highest priority)

Text-style fields declared inside `default_display` in the plugin's `manifest.json` always override both the user's per-button settings and the system default. This lets plugins enforce a specific look for their function buttons regardless of the user's preferences.

Only fields that are **explicitly declared** in the manifest take effect at plugin priority. Any field omitted from the manifest falls through to layer 2 or layer 1.

### Practical example

A user has set a system default of `text_position: "top"` and `text_bold: true`. They configure a specific Spotify button with `text_size: 12`. The Spotify plugin declares `text_position: "middle"` and `text_color: "#ffffff"` in its manifest. The resolved style is:

| Field | Value | Source |
|:---|:---|:---|
| `text_position` | `"middle"` | Plugin manifest |
| `text_color` | `"#ffffff"` | Plugin manifest |
| `text_size` | `12` | User per-button |
| `text_bold` | `true` | System default |
| All other fields | system defaults | System default |
