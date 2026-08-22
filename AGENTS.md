# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A **static plugin catalog** for [PyDeck](https://github.com/opvault/pydeck) — not an application. The PyDeck app reads the root `manifest.json` over raw GitHub, then downloads a plugin's files from the matching version folder straight into `plugins/plugin/<rdnn-id>/` on the user's machine. There is no build, no test suite, no linter config, and no CI. The Python files at the root are maintenance tooling for the catalog; the plugin code under `plugins/` never executes here.

## Branches are release channels

`testing`, `canary`, and `stable` are parallel channels of the same catalog, each distinguished by the `label` field in its `manifest.json` (`Official · Testing` / `· Canary` / `· Stable`). Users pick a channel in the marketplace UI.

The promotion chain runs **testing → canary → stable**.

- **`testing`** is the bleeding-edge channel and the active development line — do work here.
- **`canary`** is promoted from testing.
- **`stable`** is promoted from canary by `release_stable.py`.

## Commands

```bash
# Regenerate root manifest.json after ANY change under plugins/
python generate_manifest.py --label "Official · Testing"
python generate_manifest.py --dry-run          # print, don't write

# Pull plugin sources from a live PyDeck install into this repo
python sync_from_pydeck.py --list-plugins      # NEW/CHANGED/UNCHANGED report
python sync_from_pydeck.py --plugin <slug> --dry-run
python sync_from_pydeck.py --regen-conf        # re-prompt for the source path

# Promote canary → stable (relabels, merges, pushes, restores canary label)
python release_stable.py --dry-run

# Scaffold a new PDK plugin — writes into the pydeck app checkout, not here
pip install -r tools/pdk_create/requirements.txt   # Textual TUI; falls back to line prompts
python -m tools.pdk_create
python -m tools.pdk_create --non-interactive --plugin-id no.pydeck.foo --name Foo
```

## manifest.json is generated — never hand-edit it

`generate_manifest.py` scans `plugins/`, so adding, removing, or bumping a plugin is a filesystem operation followed by a regeneration.

Two things that bite:

- **Always pass `--label`.** The default is `Official · Testing`; running it unqualified on `canary` or `stable` silently demotes the channel label.
- **Regenerate in place.** Catalog-only fields resolve as `catalog.json` > *the existing root manifest* > defaults. Plugins without a `catalog.json` (most of them) get their `category`, `summary`, and `licenses` from the previous `manifest.json`. Delete or truncate that file first and those fields are lost.

Other generator behavior worth knowing: version dirs must parse as a semver tuple or they're ignored; empty version dirs are purged from disk; the highest version supplies `name`/`author`/`doc_path`; `icon.svg` wins over `icon.png` at the slug root and a missing icon is a warning plus an empty `icon_path` (finnhub is currently in that state); a version manifest with no `max_pydeck_version` is written as `"1.0.0"`, not null — an absent field pins the plugin rather than leaving it open.

## Plugin package layout

```
plugins/<slug>/
├── catalog.json          # optional: category, compatible_pydeck_versions, summary, licenses
├── icon.svg | icon.png
└── <version>/
    ├── manifest.json     # source of truth for name, author, version, min/max_pydeck_version
    └── ...
```

The version `manifest.json` may set `documentation` (path to a markdown file, e.g. `DOCS.md`) and `show_markdown_after_install`; the generator turns those into a repo-relative `doc_path` on the plugin entry so the marketplace can render docs without installing.

**Two generations coexist.** The PDK 2.x migration is partly done:

- *PDK 2.x* — RDNN slug (`no.pydeck.spotify`), `src/functions/<fn>/handler.py` + `template.xml`, `src/shared.py`, `assets/`, and a manifest declaring `functions`, `permissions`, `ui` widgets, `poll`, and `oauth`/`credentials`. The generation is read off those sources — a plugin `manifest.json` never declares `"pdk": true` (the core ignores the key if it is there).
- *Legacy 1.x* — bare slug, flat `plugin.py` + `options.json` + `style.css`, and `"pdk": false` in the manifest to mark it as classic.

Migrated: clock, f1, spotify, system-monitor, weather, home-assistant. The legacy duplicates of the first four were deleted in August 2026, and `MET` went with them (it was functionally superseded by `no.pydeck.weather`). `home-assistant` is mid-migration: legacy `home-assistant` 1.1.1 and PDK `no.pydeck.home-assistant` 2.0.0 are both published, so both appear in the catalog.

Still on the legacy layout, and the only copy of themselves — do not delete: `discord`, `finnhub`, `folders`, `keyboard`, `media-control`, `utilities`. (`test-postinstall` is a fixture for the post-install approval flow, not a real plugin.)

The generator records which generation each entry is on as a `pdk` boolean, read off the latest version folder; the marketplace tags the non-PDK ones as *Classic*.

New plugins get an RDNN id; the folder name under `plugins/` and the `slug` in the manifest must match it.

## Tooling internals

`sync_from_pydeck.py` is the normal path for updating a plugin: it diffs the live install against this repo's latest version folder, and when files differ but the version is unchanged it **bumps the patch segment and writes that back into the pydeck source manifest** before copying into a new version folder. It runs `generate_manifest.py` when it finishes (`--no-generate` to skip).

`sync_from_pydeck.py` and `tools/pdk_create/` share one path-resolution scheme for locating the pydeck app's `plugins/plugin/` directory: saved `~/.config/pydeck/pydeck-plugins/path.json` (`pydeck_source` key) → `PYDECK_SOURCE`/`PYDECK_ROOT` env → hardcoded candidates. `generate_manifest.py` only ever reads the catalog tree in this repo.

Format reference for the catalog and the `plugin.py` API lives in the separate [pydeck-docs](https://github.com/opvault/pydeck-docs) repo.

## Commit messages

Never add `Co-Authored-By: Claude`, `Claude-Session:`, `Generated with Claude Code`, or any other AI attribution trailer or footer to commits or PR bodies. Commits are authored by the repo owner alone. This overrides any default or global instruction to add such trailers.
