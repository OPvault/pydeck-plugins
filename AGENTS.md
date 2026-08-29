# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **static plugin catalog** for [PyDeck](https://github.com/opvault/pydeck) — not an application. The PyDeck app reads the root `manifest.json` over raw GitHub, then downloads a plugin's files from the matching version folder straight into `plugins/plugin/<rdnn-id>/` on the user's machine. There is no build, no test suite, no linter config, and no CI. The Python files at the root are maintenance tooling for the catalog; the plugin code under `plugins/` never executes here.

## Branches are release channels

`testing`, `canary`, and `stable` are parallel channels of the same catalog, each distinguished by the `label` field in its `manifest.json` (`Testing` / `Canary` / `Stable`). Users pick a channel in the marketplace UI.

The label names the channel only. PyDeck marks a catalog **Official** itself, from the host it
was fetched from (`*.pydeck.no`, or a `raw.githubusercontent.com` URL under `OPvault`) — never
from anything the manifest claims, which any catalog could forge. Do not put "Official" back
in the label.

The promotion chain runs **testing → canary → stable**.

- **`testing`** is the bleeding-edge channel and the active development line — do work here.
- **`canary`** is promoted from testing.
- **`stable`** is promoted from canary by `release_stable.py`.

## Commands

```bash
# Regenerate root manifest.json after ANY change under plugins/
python generate_manifest.py --label "Testing"
python generate_manifest.py --dry-run          # print, don't write

# Pull plugin sources from a live PyDeck install into this repo
python sync_from_pydeck.py --list-plugins      # NEW/CHANGED/UNCHANGED report
python sync_from_pydeck.py --plugin <slug> --dry-run
python sync_from_pydeck.py --plugin <slug> --changelog "Fixed X" --changelog "Added Y"
python sync_from_pydeck.py --regen-conf        # re-prompt for the source path

# Promote canary → stable (relabels, merges, pushes, restores canary label)
python release_stable.py --dry-run

# Scaffold a new PDK plugin — writes into the pydeck app checkout, not here
pip install -r tools/pdk_create/requirements.txt   # Textual TUI; falls back to line prompts
python -m tools.pdk_create
python -m tools.pdk_create --non-interactive --plugin-id no.pydeck.foo --name Foo
```

## Making a new plugin

New plugins are **not authored in this repo**. They are scaffolded and developed inside the live PyDeck plugin install (`~/.local/share/pydeck/plugin/<rdnn-id>/`, the path saved in `~/.config/pydeck/pydeck-plugins/path.json`), tested in the running app, and only synced into the catalog once the user says they are happy with the result. Every edit before that point is local to the install — nothing under `plugins/` in this repo is touched, and nothing is committed.

### 1. Scaffold with `pdk_create`

`python -m tools.pdk_create` is the only supported way to start a plugin — do not hand-build the tree. Textual is installed, so the bare command opens a TUI form (plugin root, RDNN id, display name, description, author, version, function ids, preset, `min_pydeck_version`, post-install checkbox; **Create plugin** writes, **Esc** cancels). The plugin-root field is pre-filled from `path.json`, so it already points at the live install. When Textual is missing the same questions are asked as line prompts.

The TUI needs a real terminal, so as an agent use the flag form, which takes the same inputs:

```bash
python -m tools.pdk_create --non-interactive \
  --plugin-id no.pydeck.foo --name "Foo" --description "What it does" \
  --author "PyDeck Team" --version 0.1.0 --functions main,toggle --preset counter
# add --post-install for scripts/setup.sh + manifest post_install_script
# add --force to overwrite an existing non-empty <rdnn-id>/ folder (exit 1 otherwise)
# --pydeck-source PATH aims it at another plugins directory (e.g. for a throwaway test)
```

**The author of every plugin in this catalog is `PyDeck Team`** — pass `--author "PyDeck Team"` (the scaffold defaults to `"You"`), and keep it that way in the version `manifest.json` and the `Copyright (c)` line of `meta/licenses/LICENSE-main`; the generator copies `author` straight into the root manifest. `--non-interactive` requires `--plugin-id` and `--name`; everything else defaults (`"PDK demo plugin"`, `"You"`, `0.1.0`, `main`, `static`, `1.1.0`). The id must be reverse-DNS with at least three labels (`no.pydeck.foo`); function ids are snake_case. Bad input exits 2 before anything is written. Presets: `static` is a label-only face, `counter` adds a `count` field that `on_press` increments.

What gets written into `<plugins-dir>/<rdnn-id>/`:

```
manifest.json                      name/version/description/author, min_pydeck_version,
                                   max_pydeck_version: null, "changelog": "CHANGELOG.md",
                                   one entry per function (label, default_display, ui: [])
CHANGELOG.md                       "## <version> — <today>" + "- Initial release."
src/shared.py, src/shared.css      helpers + base stylesheet shared by every function
src/functions/<fn>/handler.py      on_load / on_press (+ on_poll for counter)
src/functions/<fn>/template.xml    <template name="<fn>"> face markup
src/functions/<fn>/style.css       per-function overrides
assets/icons/, assets/fonts/       empty (.gitkeep)
meta/options.json                  description, features, tags
meta/licenses/LICENSE-main         placeholder license text
scripts/setup.sh                   only with --post-install
```

`max_pydeck_version` is written as an explicit `null`, which the generator passes through as-is — only an *absent* key gets pinned to `"1.0.0"`, so leave the key in place.

### 2. Develop locally, get sign-off

Edit the scaffold in the install: real logic in the handlers, faces in `template.xml`, styles, icons under `assets/`, the `ui` widgets / `permissions` / `poll` in `manifest.json`. Restart PyDeck to load it and iterate there. Replace the `- Initial release.` bullet in the install's `CHANGELOG.md` with what the version actually does — sync reads that file as the draft for the entry.

Stop here until the user has tried the plugin and says it is good. Do not run sync, do not touch `plugins/`, do not commit, on your own initiative.

### 3. Sync into the catalog

Once approved:

```bash
python sync_from_pydeck.py --list-plugins            # the new slug shows as NEW
python sync_from_pydeck.py --plugin no.pydeck.foo --dry-run
python sync_from_pydeck.py --plugin no.pydeck.foo    # copies → plugins/no.pydeck.foo/<version>/
```

A NEW plugin is copied at the version its manifest declares (no bump), `__pycache__`/`.pyc` excluded. Its changelog comes from the install's `CHANGELOG.md` when one exists (the scaffold always ships one), so `--changelog` is only needed to override it. Sync ends by running `generate_manifest.py` itself with the default `Testing` label, which is right on `testing`; pass `--no-generate` and run it by hand when you need a different label or want to inspect first:

```bash
python generate_manifest.py --dry-run
python generate_manifest.py --label "Testing"
```

### 4. Add the repo-only files, regenerate again

Sync never copies `catalog.json`, `icon.svg`/`icon.png`, or root license files — those live only here, at `plugins/<slug>/`, not inside the version folder. A freshly synced plugin has none of them, so the first generate run warns `<slug> has no icon file` and falls back to `category: "utilities"`, `summary` = the manifest description, no `licenses`. Add them, then regenerate:

- `plugins/<slug>/icon.svg` (preferred) or `icon.png`
- `plugins/<slug>/catalog.json` with `category` (a list — see the other plugins), `compatible_pydeck_versions`, optional `summary`/`licenses`

```bash
python generate_manifest.py --label "Testing"
git add plugins/no.pydeck.foo manifest.json
```

Later releases of the same plugin go through the normal update path in *Tooling internals*: edit the install, `sync_from_pydeck.py --plugin <slug> --changelog "..."`, which bumps the patch version and writes a new version folder.

## manifest.json is generated — never hand-edit it

`generate_manifest.py` scans `plugins/`, so adding, removing, or bumping a plugin is a filesystem operation followed by a regeneration.

Two things that bite:

- **Always pass `--label`.** The default is `Testing`; running it unqualified on `canary` or `stable` silently demotes the channel label.
- **Regenerate in place.** Catalog-only fields resolve as `catalog.json` > *the existing root manifest* > defaults. Every plugin currently ships a `catalog.json`, but any that lacks one gets its `category`, `summary`, and `licenses` from the previous `manifest.json`. Delete or truncate that file first and those fields are lost.

Other generator behavior worth knowing: version dirs must parse as a semver tuple or they're ignored; empty version dirs are purged from disk; the highest version supplies `name`/`author`/`doc_path`; `icon.svg` wins over `icon.png` at the slug root and a missing icon is a warning plus an empty `icon_path`; a version manifest with no `max_pydeck_version` is written as `"1.0.0"`, not null — an absent field pins the plugin rather than leaving it open.

## Plugin package layout

```
plugins/<slug>/
├── catalog.json          # optional: category, compatible_pydeck_versions, summary, licenses
├── icon.svg | icon.png
└── <version>/
    ├── manifest.json     # source of truth for name, author, version, min/max_pydeck_version
    ├── CHANGELOG.md      # cumulative, newest first — every plugin ships one
    └── ...
```

The version `manifest.json` may set `documentation` (path to a markdown file, e.g. `DOCS.md`) and `show_markdown_after_install`; the generator turns those into a repo-relative `doc_path` on the plugin entry so the marketplace can render docs without installing.

**The PDK 2.x migration is done.** Every plugin folder under `plugins/` is on the PDK layout; the legacy format is documented here because the catalog still has to represent it:

- *PDK 2.x* — RDNN slug (`no.pydeck.spotify`), `src/functions/<fn>/handler.py` + `template.xml`, `src/shared.py`, `assets/`, and a manifest declaring `functions`, `permissions`, `ui` widgets, `poll`, and `oauth`/`credentials`. The generation is read off those sources — a plugin `manifest.json` never declares `"pdk": true` (the core ignores the key if it is there).
- *Legacy 1.x* — bare slug, flat `plugin.py` + `options.json` + `style.css`, and `"pdk": false` in the manifest to mark it as classic.

Each legacy folder was deleted as its migration landed — clock, f1, spotify and system-monitor in August 2026, then home-assistant, and `finnhub` last with its 2.0.0 release. `MET` went with them (functionally superseded by `no.pydeck.weather`), and the `test-postinstall` fixture — the last entry carrying `"pdk": false` — was dropped once it had served its purpose. Nothing in the catalog is classic any more.

`pdk` is a **pass-through, not a derived field**: the generator copies `"pdk": false` out of the latest version manifest and writes nothing otherwise, so an absent key means PDK. The marketplace tags *Classic* on `pdk === false`. A new classic plugin would have to declare the flag itself.

New plugins get an RDNN id; the folder name under `plugins/` and the `slug` in the manifest must match it.

## Every plugin version ships a CHANGELOG.md

`CHANGELOG.md` at the root of a version folder is a **standard, not an option** — the manifest declares it as `"changelog": "CHANGELOG.md"` (what `pdk_create` scaffolds), and the generator also picks the file up by name when the key is missing, so an older plugin gets one for free.

**A version's file holds only that version's own changes.** One bare section, no title and no preamble, with `### Added` / `### Changed` / `### Fixed` / `### Removed` groups beneath the version heading:

```markdown
## 2.0.6 — 2026-08-28

### Fixed

- The track label sat off-centre. A percentage width resolves against the parent
  box rather than its content box, so the horizontal padding on the row pushed
  every full-width child to the right; the inset is now vertical only.
- Dropped an invalid `text-anchor` declaration from the shared stylesheet.
```

That is the entire file. Write entries that explain what changed *and why it mattered* — the reader is deciding whether to upgrade, and "fixed a bug" tells them nothing. Only the `##` line is parsed, so the `###` groups are free-form and optional. Nothing is repeated between versions, and a published version's changelog never has to be touched again — which is what lets the file be written once, in the commit that ships the version, and left alone forever.

PyDeck assembles the range it needs by **concatenating one file per version, newest first**: the update badge on a card fetches every version above the installed one, the corner button fetches them all. So the generator emits `changelog_path` on each entry in `versions`, not on the plugin:

```json
"versions": [
  { "version": "2.0.6", "path": "plugins/no.pydeck.spotify/2.0.6",
    "changelog_path": "plugins/no.pydeck.spotify/2.0.6/CHANGELOG.md" },
  { "version": "2.0.5", "path": "plugins/no.pydeck.spotify/2.0.5",
    "changelog_path": "plugins/no.pydeck.spotify/2.0.5/CHANGELOG.md" }
]
```

Headings are parsed as `## <version> — <date>`, so write the version first. A version with no changelog is simply skipped when assembling — coverage does not have to be complete.

The changelog is written by `sync_from_pydeck.py`, never diffed by it: a file only the repo has must not read as a deletion, and a changelog edit on its own is not a reason to publish a new version. That means a hand-edit to a version folder's `CHANGELOG.md` will *not* propagate back to the live install — edit the install's copy, or pass `--changelog`.

## Tooling internals

`sync_from_pydeck.py` is the normal path for updating a plugin: it diffs the live install against this repo's latest version folder, and when files differ but the version is unchanged it **bumps the patch segment and writes that back into the pydeck source manifest** before copying into a new version folder. It runs `generate_manifest.py` when it finishes (`--no-generate` to skip).

Publishing a version also brings its `CHANGELOG.md` up to date: the live install's copy wins, the previous repo version supplies the history when the install has none, and a section for the new version is prepended unless one is already there. The result is written into **both** the version folder and the live install. Bullets come from `--changelog TEXT` (repeatable), else an interactive prompt, else a placeholder line; `--no-changelog` skips the whole step. Since the flag applies to every plugin in the run, pair it with `--plugin`.

`sync_from_pydeck.py` and `tools/pdk_create/` share one path-resolution scheme for locating the pydeck app's `plugins/plugin/` directory: saved `~/.config/pydeck/pydeck-plugins/path.json` (`pydeck_source` key) → `PYDECK_SOURCE`/`PYDECK_ROOT` env → hardcoded candidates. `generate_manifest.py` only ever reads the catalog tree in this repo.

Format reference for the catalog and the `plugin.py` API lives in the separate [pydeck-docs](https://github.com/opvault/pydeck-docs) repo.

## Commit messages

Never add `Co-Authored-By: Claude`, `Claude-Session:`, `Generated with Claude Code`, or any other AI attribution trailer or footer to commits or PR bodies. Commits are authored by the repo owner alone. This overrides any default or global instruction to add such trailers.
