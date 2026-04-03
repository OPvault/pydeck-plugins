# PyDeck Marketplace Repo Guide

Everything you need to understand how the PyDeck marketplace works, how the two repos relate to each other, and how to maintain a plugin catalog repo.

---

## Table of Contents

1. [Two-Repo Architecture](#1-two-repo-architecture)
2. [The Plugin Catalog Repo — Layout](#2-the-plugin-catalog-repo--layout)
3. [Root manifest.json — Catalog Format](#3-root-manifestjson--catalog-format)
4. [Plugin Version Folders](#4-plugin-version-folders)
5. [How PyDeck Installs a Plugin](#5-how-pydeck-installs-a-plugin)
6. [Version Path Rules](#6-version-path-rules)
7. [Adding a New Plugin](#7-adding-a-new-plugin)
8. [Adding a New Version of an Existing Plugin](#8-adding-a-new-version-of-an-existing-plugin)
9. [Removing a Plugin](#9-removing-a-plugin)
10. [Compatibility Fields](#10-compatibility-fields)
11. [How PyDeck Resolves the Catalog URL](#11-how-pydeck-resolves-the-catalog-url)
12. [Common Errors and Fixes](#12-common-errors-and-fixes)

---

## 1. Two-Repo Architecture

PyDeck uses two separate GitHub repositories.

```
┌─────────────────────────────────┐       ┌─────────────────────────────────────┐
│  pydeck  (main app repo)        │       │  pydeck-plugins  (catalog repo)     │
│                                 │       │                                     │
│  start.py  ─── Flask app        │       │  manifest.json  ── catalog index    │
│  marketplace/  ─── installer    │──────▶│  plugins/                           │
│  plugins/plugin/  ─── local     │       │    <slug>/                          │
│    plugins installed here       │       │      <version>/                     │
│                                 │       │        manifest.json                │
│                                 │       │        plugin.py                    │
│                                 │       │        ...                          │
└─────────────────────────────────┘       └─────────────────────────────────────┘
         user runs this                            hosted on GitHub
```

**The main app repo (`pydeck`)** runs on the user's machine. It contains the Flask server, the hardware listener, the web UI, and the local `plugins/plugin/` directory where installed plugins live.

**The catalog repo (`pydeck-plugins`)** is hosted on GitHub. It contains:
- A root `manifest.json` that lists every available plugin and its versions.
- One folder per plugin version with all the plugin's files.

When a user installs a plugin through the marketplace UI, PyDeck fetches the catalog, reads the plugin's version path, then downloads the files directly from the catalog repo into `plugins/plugin/<slug>/` on the user's machine.

The two repos are **independent**. The catalog repo has no code that runs — it is purely a file store and manifest. PyDeck accesses it entirely via the GitHub raw file API and the Git tree API.

---

## 2. The Plugin Catalog Repo — Layout

```
<catalog-repo-root>/
├── manifest.json                  # ← Root catalog index (REQUIRED)
│
└── plugins/                       # ← One subfolder per plugin
    ├── browser/
    │   └── 1.0.0/                 # ← One subfolder per version
    │       ├── manifest.json
    │       └── plugin.py
    │
    ├── spotify/
    │   ├── 1.0.0/
    │   │   ├── manifest.json
    │   │   ├── plugin.py
    │   │   ├── spotify_client.py
    │   │   ├── style.css
    │   │   └── options.json
    │   └── 1.1.0/
    │       ├── manifest.json
    │       ├── plugin.py
    │       └── spotify_client.py
    │
    └── clock/
        └── 1.0.0/
            ├── manifest.json
            └── plugin.py
```

Rules:
- Each plugin gets **one directory** directly under `plugins/`.
- The directory name is the plugin's **slug** (also used as the install directory name on the user's machine).
- Inside the plugin directory, each released version gets **its own subdirectory** named after the version string (e.g. `1.0.0`).
- All plugin files for that version live inside the version directory.
- Version directories are siblings — they do not nest.

The path `plugins/browser/1.0.0` is called the **version path**. The parent `plugins/browser` is the **plugin base**.

> **The `plugins/` prefix shown above assumes the catalog repo root contains a `plugins/` directory.** Your actual prefix may differ — what matters is that the `path` values in `manifest.json` (see below) exactly match the real directory paths in the repo.

---

## 3. Root `manifest.json` — Catalog Format

The root `manifest.json` at the repo root is the single file PyDeck fetches first. It must be valid JSON.

### Full example

```json
{
  "schema_version": 1,
  "generated_at": "2026-04-03T00:00:00Z",
  "plugins": [
    {
      "name": "Browser",
      "slug": "browser",
      "category": "utilities",
      "summary": "Open URLs in the default browser",
      "author": "PyDeck Team",
      "latest": "1.0.0",
      "icon_path": "plugins/browser/icon.png",
      "compatible_pydeck_versions": ["1.0.0"],
      "versions": [
        {
          "version": "1.0.0",
          "path": "plugins/browser/1.0.0"
        }
      ]
    },
    {
      "name": "Spotify",
      "slug": "spotify",
      "category": "media",
      "summary": "Control Spotify playback via the Web API",
      "author": "PyDeck Team",
      "latest": "1.1.0",
      "icon_path": "plugins/spotify/icon.png",
      "compatible_pydeck_versions": ["1.0.0"],
      "versions": [
        {
          "version": "1.0.0",
          "path": "plugins/spotify/1.0.0"
        },
        {
          "version": "1.1.0",
          "path": "plugins/spotify/1.1.0",
          "min_pydeck_version": "1.0.0"
        }
      ]
    }
  ]
}
```

### Top-level fields

| Field | Type | Required | Description |
|:---|:---|:---|:---|
| `schema_version` | integer | No | Catalog schema version. Use `1`. |
| `generated_at` | string | No | ISO 8601 timestamp. Informational only. |
| `plugins` | array | **Yes** | Array of plugin entries. See below. |

### Plugin entry fields

| Field | Type | Required | Description |
|:---|:---|:---|:---|
| `name` | string | **Yes** | Human-readable display name (e.g. `"Spotify"`). |
| `slug` | string | **Yes** | Machine identifier. Must match the plugin folder name under `plugins/` in the catalog repo, and becomes the install folder name under `plugins/plugin/` on the user's machine. Lowercase, no spaces. |
| `category` | string | **Yes** | Category label used for filtering (e.g. `"media"`, `"utilities"`, `"system"`). |
| `summary` | string | **Yes** | One-line description shown in the marketplace card. |
| `author` | string | **Yes** | Author name. |
| `latest` | string | **Yes** | The version string that should be installed by default. Must match a `version` value in the `versions` array. |
| `icon_path` | string | **Yes** | Repo-relative path to the plugin's icon image (e.g. `"plugins/spotify/icon.png"`). The image is shown in the marketplace card. |
| `compatible_pydeck_versions` | array of strings | **Yes** | List of PyDeck version strings this plugin is compatible with. Used for filtering. |
| `versions` | array | **Yes** | Array of version entries. Must contain at least one entry. |

### Version entry fields

| Field | Type | Required | Description |
|:---|:---|:---|:---|
| `version` | string | **Yes** | Semantic version string (e.g. `"1.0.0"`). Must be unique within the plugin's `versions` array. |
| `path` | string | **Yes** | Repo-relative path to the version folder (e.g. `"plugins/spotify/1.1.0"`). **This path must exactly match the real directory in the repo.** |
| `min_pydeck_version` | string | No | Minimum PyDeck version required for this plugin version. |
| `max_pydeck_version` | string | No | Maximum PyDeck version supported by this plugin version. |

---

## 4. Plugin Version Folders

Each version folder contains the actual plugin files that get installed on the user's machine. After install, the contents of the version folder are placed flat inside `plugins/plugin/<slug>/` on the user's machine — the version directory itself is not included.

**Repo structure:**
```
plugins/spotify/1.1.0/
├── manifest.json
├── plugin.py
├── spotify_client.py
└── style.css
```

**After install on user's machine:**
```
plugins/plugin/spotify/
├── manifest.json
├── plugin.py
├── spotify_client.py
└── style.css
```

The version directory name (`1.1.0`) is stripped. Everything inside it lands at the root of the plugin folder.

### Required files in a version folder

| File | Required | Purpose |
|:---|:---|:---|
| `manifest.json` | **Yes** | Local plugin manifest (different from the catalog root `manifest.json`). Declares functions, UI, credentials, OAuth, and permissions. See [PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md) §3 for the full format. |
| `plugin.py` | **Yes** | Python functions called on button press. |
| `style.css` | No | Custom CSS. Automatically served by the core. |
| `options.json` | No | Extra marketplace metadata (features, tags). |
| `img/` | No | Image assets served via the plugin image API. |
| `*.py` | No | Additional Python helper modules. |

### The local `manifest.json` inside a version folder

This is **not** the same format as the root catalog `manifest.json`. It is the plugin's own metadata file read by the running PyDeck app after install:

```json
{
  "name": "Spotify",
  "version": "1.1.0",
  "description": "Control Spotify playback via the Web API",
  "author": "PyDeck Team",
  "slug": "spotify",
  "entrypoint": "plugin.py",
  "credentials": [
    { "id": "client_id", "label": "Client ID", "type": "text" },
    { "id": "client_secret", "label": "Client Secret", "type": "password" }
  ],
  "permissions": {
    "urllib.request": ["urlopen", "Request"]
  },
  "functions": {
    "play_pause": {
      "label": "Play / Pause",
      "ui": []
    }
  }
}
```

See [PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md) for the complete `manifest.json` reference.

---

## 5. How PyDeck Installs a Plugin

Understanding this flow is critical for maintaining the catalog repo correctly.

### Step 1 — Fetch the catalog

PyDeck fetches the root `manifest.json` from a URL like:
```
https://raw.githubusercontent.com/opvault/pydeck-plugins/main/manifest.json
```

### Step 2 — Resolve the install target

From the catalog entry, PyDeck reads:
- `slug` → used as the install directory name (`plugins/plugin/<slug>/`)
- The chosen `version.path` (e.g. `plugins/spotify/1.1.0`)

It splits the path into:
- **plugin base**: everything except the last segment → `plugins/spotify`
- **selected version**: the last segment → `1.1.0`
- **other version names**: all version strings in the `versions` array

### Step 3 — List files via the GitHub Tree API

PyDeck calls the GitHub Git Tree API:
```
GET https://api.github.com/repos/<owner>/<repo>/git/trees/<ref>?recursive=1
```

This returns a list of every file path in the repo (relative to the repo root).

### Step 4 — Filter files for the target version

PyDeck keeps every path that:
- Starts with `plugins/spotify/` (the plugin base + `/`)
- Is **not** inside another version directory (e.g. `plugins/spotify/1.0.0/...` is excluded when installing `1.1.0`)

Files directly under the plugin base that are not inside any version subdirectory are also included (e.g. `plugins/spotify/icon.png`).

### Step 5 — Download each file

PyDeck downloads each matching file from:
```
https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<path>
```

The version prefix is stripped before writing — so `plugins/spotify/1.1.0/plugin.py` is saved to the user's machine as `plugins/plugin/spotify/plugin.py`.

### What causes install to fail

The most common install failure:

> `FileNotFoundError: No files found for plugin scope: plugins/spotify`

**Cause:** The GitHub Tree API returned zero files starting with `plugins/spotify/`. This happens when:
1. The version folder referenced in `path` does not exist in the repo, **or**
2. The `path` value in the catalog `manifest.json` does not match the actual directory structure in the repo.

**Fix:** Either add the missing files, or remove/correct the entry in `manifest.json`.

---

## 6. Version Path Rules

The `path` value in each version entry is the most important field to get right. It must:

1. **Be relative to the repo root** — no leading slash, no `https://`, no branch name.
2. **Match the actual directory in the repo exactly** — case-sensitive on GitHub.
3. **Include only one level of versioning** — `plugins/spotify/1.1.0`, not `plugins/spotify/releases/1.1.0`.
4. **Not end with a slash** — `plugins/spotify/1.1.0`, not `plugins/spotify/1.1.0/`.

### Correct

```json
{ "version": "1.1.0", "path": "plugins/spotify/1.1.0" }
```

Files exist in the repo at `plugins/spotify/1.1.0/manifest.json`, `plugins/spotify/1.1.0/plugin.py`, etc.

### Wrong — repo name included in path

```json
{ "version": "1.0.0", "path": "pydeck-plugins/plugins/browser/1.0.0" }
```

Paths returned by the GitHub Tree API are relative to the repo root — the repo name is not part of the path.

### Wrong — path doesn't exist in repo

```json
{ "version": "1.0.0", "path": "plugins/browser/1.0.0" }
```

If `plugins/browser/1.0.0/` doesn't exist as a real directory in the repo, the install will fail with "No files found for plugin scope".

---

## 7. Adding a New Plugin

### 1. Create the version folder in the catalog repo

```
plugins/<slug>/<version>/
├── manifest.json   ← local plugin manifest
├── plugin.py
└── (any other files)
```

If you have a plugin icon, place it at `plugins/<slug>/icon.png` (or any path, as long as it matches `icon_path` in the catalog manifest).

### 2. Add the entry to the root `manifest.json`

```json
{
  "name": "My Plugin",
  "slug": "my_plugin",
  "category": "utilities",
  "summary": "Does something useful",
  "author": "Your Name",
  "latest": "1.0.0",
  "icon_path": "plugins/my_plugin/icon.png",
  "compatible_pydeck_versions": ["1.0.0"],
  "versions": [
    {
      "version": "1.0.0",
      "path": "plugins/my_plugin/1.0.0"
    }
  ]
}
```

### 3. Commit and push both changes together

The catalog `manifest.json` and the version folder files must be committed and pushed in the same operation (or at least before any install is attempted). If `manifest.json` references a version path that hasn't been pushed yet, installs will fail.

### Checklist

- [ ] `plugins/<slug>/<version>/` directory exists in the repo
- [ ] `plugins/<slug>/<version>/manifest.json` exists and is valid JSON with at minimum `name`, `version`, `description`, `author` fields
- [ ] `plugins/<slug>/<version>/plugin.py` exists
- [ ] Root `manifest.json` has a new entry for the plugin with `slug`, `latest`, `versions[].path` matching the directory above
- [ ] Icon file exists at the path specified in `icon_path` (or remove the field)
- [ ] Changes are pushed to the branch referenced by the catalog URL (usually `main`)

---

## 8. Adding a New Version of an Existing Plugin

### 1. Create the new version folder

```
plugins/<slug>/<new_version>/
├── manifest.json   ← update the version field inside to match
├── plugin.py
└── ...
```

### 2. Update root `manifest.json`

Add the new version to the `versions` array **and** update `latest` if this is the new recommended version:

```json
{
  "slug": "spotify",
  "latest": "1.1.0",
  "versions": [
    {
      "version": "1.0.0",
      "path": "plugins/spotify/1.0.0"
    },
    {
      "version": "1.1.0",
      "path": "plugins/spotify/1.1.0"
    }
  ]
}
```

Keep the old version entry so users who have it installed can still fetch metadata for it (used by the update checker). Do not delete old version folders from the repo unless you want to break installs of that specific version.

### 3. Commit and push

Push the new version folder and the updated `manifest.json` together.

---

## 9. Removing a Plugin

### Full removal (plugin discontinued)

1. Delete the plugin's entry from the root `manifest.json` `plugins` array.
2. Optionally delete the `plugins/<slug>/` directory from the repo (only do this if you are sure no users have it installed and no other references exist).
3. Commit and push.

If `manifest.json` no longer lists the plugin, PyDeck's catalog will not show it. Existing installs on user machines are unaffected until the user uninstalls.

### Temporary removal (hide from catalog)

Remove the entry from `manifest.json` without deleting the files. The files remain in the repo but the plugin won't appear in the marketplace.

---

## 10. Compatibility Fields

### `compatible_pydeck_versions` (plugin entry level)

Used for catalog search filtering. When a user's PyDeck version is not in this list, the plugin may be hidden or marked incompatible in the UI.

```json
"compatible_pydeck_versions": ["1.0.0", "1.1.0"]
```

### `min_pydeck_version` / `max_pydeck_version` (version entry level)

Used by PyDeck's update checker to determine which versions of a plugin are valid for the running PyDeck version. If the user's PyDeck version is outside this range, that plugin version won't be offered as an upgrade.

```json
{
  "version": "2.0.0",
  "path": "plugins/spotify/2.0.0",
  "min_pydeck_version": "1.2.0"
}
```

This is optional. If omitted, the version is considered compatible with all PyDeck versions.

---

## 11. How PyDeck Resolves the Catalog URL

PyDeck determines the catalog URL(s) to use in the following priority order (first non-empty source wins, duplicates dropped):

1. **Environment variable** `PYDECK_MARKETPLACE_MANIFEST_URL` — comma-separated list of URLs.
2. **Config file** `~/.config/pydeck/core/config.json` → `marketplace_manifest_urls` (list of strings).
3. **Config file** (legacy) → `marketplace_manifest_url` (single string).
4. **Built-in default** — the URL compiled into `start.py` as `_DEFAULT_MARKETPLACE_MANIFEST_URLS`.

The catalog URL must be a `raw.githubusercontent.com` URL pointing to the `manifest.json` file:

```
https://raw.githubusercontent.com/<owner>/<repo>/<branch>/manifest.json
```

PyDeck derives the GitHub owner, repo, and branch from this URL and uses them for **all** API calls (tree API and raw file downloads). The catalog URL and the plugin files must be in the **same repo and branch**.

GitHub repo page URLs (e.g. `https://github.com/owner/repo`) are automatically converted to raw manifest URLs pointing to `main` branch when entered in the UI.

---

## 12. Common Errors and Fixes

### `No files found for plugin scope: plugins/<slug>`

**Cause:** The `path` in `manifest.json` points to a version folder that has no files in the repo tree (either the folder doesn't exist, or the path is wrong).

**Fix:**
- Verify the folder `plugins/<slug>/<version>/` exists in the repo and has been pushed.
- Verify the `path` value in `manifest.json` exactly matches the folder path relative to the repo root.
- If the plugin was removed intentionally, remove its entry from `manifest.json`.

### `Unknown plugin in this catalog: <slug>`

**Cause:** The `slug` sent in the install request does not match any plugin entry in the fetched catalog manifest.

**Fix:** Verify the `slug` field in `manifest.json` is spelled correctly and has no extra whitespace.

### `Version '<x>' does not exist for plugin '<slug>'`

**Cause:** The version string requested for install is not present in the plugin's `versions` array.

**Fix:** Add the version entry (and its files) or correct the `latest` field to point to a version that exists.

### `Install needs a catalog URL on raw.githubusercontent.com`

**Cause:** The catalog URL is not a `raw.githubusercontent.com` URL. PyDeck cannot derive the owner/repo/branch to download plugin files.

**Fix:** Configure the catalog URL as `https://raw.githubusercontent.com/<owner>/<repo>/<branch>/manifest.json`. GitHub repo page URLs are accepted in the settings UI and converted automatically.

### Install silently installs an empty plugin (no functions appear)

**Cause:** The version folder exists but is missing `manifest.json` or `plugin.py`.

**Fix:** Add both required files to the version folder and push.
