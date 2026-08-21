# pydeck-plugins

The official plugin catalog for [PyDeck](https://github.com/opvault/pydeck). This repo acts as a marketplace — PyDeck fetches plugin metadata and files directly from here when a user installs or updates a plugin.

## How it works

PyDeck uses a two-repo architecture:

- **pydeck** — the main app that runs on your machine (Flask server, hardware listener, web UI)
- **pydeck-plugins** *(this repo)* — a static file store and manifest, hosted on GitHub

When you install a plugin through the marketplace UI, PyDeck reads the root `manifest.json` to find the plugin, then downloads its files from the matching version folder directly into `plugins/plugin/<rdnn-id>/` on your machine (reverse-DNS plugin id, e.g. `no.pydeck.spotify`).

## Available plugins

| Plugin | Category | Summary |
|:---|:---|:---|
| Browser | Utilities | Open URLs in the default browser |
| Clock | Utilities | Display a live digital clock on a button |
| Discord | Communication | Control Discord voice state (mute/deafen) via RPC |
| Home Assistant | Home Automation | Control and monitor Home Assistant entities |
| Media Control | Media | Control media playback on Linux |
| Spotify | Media | Control Spotify playback via the Web API |
| Web Requests | Utilities | Send HTTP requests with a configurable method and payload |

## Repo structure

```
pydeck-plugins/
├── manifest.json              # Root catalog index — lists all plugins and versions
└── plugins/
    └── <rdnn-id>/
        ├── icon.svg
        └── <version>/
            ├── manifest.json  # Plugin metadata read by PyDeck after install
            ├── plugin.py      # Python functions called on button press
            ├── DOCS.md        # Optional: bundled markdown docs (see below)
            └── ...            # Any additional files (CSS, helpers, assets)
```

## Plugin documentation (markdown)

A plugin version can ship a markdown file (e.g. `DOCS.md`) that PyDeck renders in
the marketplace and, optionally, as a popup right after installation. Two fields in
the version's `manifest.json` drive this:

| Field | Type | Meaning |
|:---|:---|:---|
| `documentation` | string | Path to the markdown file, relative to the version folder (e.g. `"DOCS.md"`). |
| `show_markdown_after_install` | bool | `true` → PyDeck pops the rendered doc up automatically after install. `false`/absent → the doc is only shown when the user opens the plugin in the marketplace. |

`generate_manifest.py` reads these from the **latest** version's manifest and adds a
repo-relative `doc_path` (e.g. `plugins/discord/1.1.4/DOCS.md`) plus
`show_markdown_after_install` to the plugin's entry in the root `manifest.json`, so the
marketplace can fetch and render the doc without installing first. The markdown file is
downloaded with the plugin like any other file, so installed plugins can render it from
disk too.

## PDK plugin creator (development)

To generate a new **PDK** plugin tree directly inside a local **pydeck** checkout (`plugins/plugin/<rdnn-id>/`), use the scaffold tool:

```bash
pip install -r tools/pdk_create/requirements.txt   # Textual TUI (interactive mode)
python -m tools.pdk_create
```

Without Textual, interactive mode falls back to line prompts. It resolves the `plugins/plugin/` directory the same way as **`sync_from_pydeck.py`** (saved `~/.config/pydeck/pydeck-plugins/path.json`, `PYDECK_SOURCE`, candidates, etc.). If you already configured sync, no extra path setup is needed.

Documentation: [PDK Plugin Creator](https://docs.pydeck.no/pydeck-plugins/PDK_CREATE/) (pydeck-docs).

## Adding a plugin

1. Create the version folder: `plugins/<rdnn-id>/<version>/` with at minimum `manifest.json` and `plugin.py`.
2. Add an entry to the root `manifest.json` with the correct `slug` (same RDNN id as the folder), `latest`, and `versions[].path`.
3. Commit and push both changes together.

See the [pydeck-docs](https://github.com/opvault/pydeck-docs) repo for the full catalog format reference and plugin manifest and `plugin.py` API.
