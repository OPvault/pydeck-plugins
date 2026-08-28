#!/usr/bin/env python3
"""Generate the root manifest.json for the pydeck-plugins marketplace repo.

Usage
-----
    python generate_manifest.py [options]

Options
-------
    --label TEXT      Catalog label string (default: "Testing")
    --output PATH     Output file path     (default: manifest.json)
    --dry-run         Print the result to stdout instead of writing it

Syncing from a live PyDeck install
----------------------------------
Use **``sync_from_pydeck.py``** in this repo to copy plugin sources into
``plugins/<slug>/<version>/``. That script resolves the install directory the
same way as the app: **``$XDG_DATA_HOME/pydeck/plugin``** (default
**``~/.local/share/pydeck/plugin``**), then legacy **``<checkout>/plugins/plugin``**
paths. This file only reads the **catalog** tree under ``plugins/`` here.

Discovery logic
---------------
For each plugins/<slug>/ directory:

  1. Version directories are any sub-folders whose name parses as a semver
     tuple (e.g. "1.0.0", "1.0.1").  They are sorted newest-first; the
     highest becomes `latest`.

  2. Per-version fields (name, description → summary, author,
     min_pydeck_version, max_pydeck_version) are read from the version's
     own manifest.json.  If the latest version's manifest declares a
     "documentation" file (markdown), the entry also gets a "doc_path"
     (repo-relative path to that file) and "show_markdown_after_install".

     Every version folder is also probed for a changelog, which becomes that
     version's "changelog_path" inside "versions".  Each file holds only its
     own version's changes, so the marketplace stitches the range it needs
     together rather than slicing one cumulative file.  The manifest's
     "changelog" key names the file explicitly; CHANGELOG.md is the
     conventional fallback every plugin gets without declaring anything.

  3. Catalog-only fields (category, compatible_pydeck_versions, summary
     override) are read from an optional plugins/<slug>/catalog.json.
     When that file is absent the script falls back to the matching entry
     in the existing root manifest.json so nothing is lost on regeneration.

  4. The icon path is auto-detected: icon.svg is preferred over icon.png.

  5. "pdk" is copied through only when the latest version's manifest declares
     it as false, which is how a classic plugin marks itself.  It is never
     derived from the version folder and never written as true: an absent key
     means PDK, and the marketplace tags Classic on `pdk === false`.

Plugins are written in alphabetical order by name.
"""

from __future__ import annotations

import argparse
import json
import re
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Repo layout ────────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).resolve().parent
PLUGINS_DIR  = REPO_ROOT / "plugins"
ROOT_MANIFEST = REPO_ROOT / "manifest.json"

SCHEMA_VERSION = 1
DEFAULT_LABEL  = "Testing"
DEFAULT_PYDECK = "1.0.0"
ICON_PRIORITY  = ("icon.svg", "icon.png")
# Conventional changelog filename, used when a version manifest does not name
# one itself. Shipping this file is all a plugin has to do to get a changelog.
CHANGELOG_FILE = "CHANGELOG.md"


def default_pydeck_plugin_install_dir() -> Path:
    """Same default as ``sync_from_pydeck`` first candidate: live PyDeck plugin data dir."""

    raw = (os.environ.get("XDG_DATA_HOME") or "").strip()
    base = Path(raw).expanduser().resolve() if raw else Path.home() / ".local" / "share"
    return base / "pydeck" / "plugin"


# ── root_url ──────────────────────────────────────────────────────────────────
# The manifest is fetched from a vanity domain that proxies it, so consumers
# cannot derive where the files live from the URL they fetched. root_url states
# it outright: the base every icon_path / version path hangs off.

ROOT_URL_TEMPLATE = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"


def _git_output(*args: str) -> str:
    import subprocess
    try:
        r = subprocess.run(["git", *args], cwd=REPO_ROOT,
                           capture_output=True, text=True)
    except OSError:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def default_root_url() -> str:
    """Raw base for the checked-out branch, or "" when it cannot be determined.

    Only a default: any script that writes a manifest for a branch other than
    the one it is standing on must pass --root-url explicitly.
    """

    remote = _git_output("remote", "get-url", "origin")
    branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", remote)
    if not m or not branch or branch == "HEAD":
        return ""
    return ROOT_URL_TEMPLATE.format(owner=m.group(1), repo=m.group(2), branch=branch)


# ── Semver helpers ─────────────────────────────────────────────────────────────

def _semver_tuple(version: str) -> Tuple[int, ...]:
    """Return a sortable tuple for a semver string, e.g. "1.0.1" → (1, 0, 1)."""
    try:
        return tuple(int(x) for x in version.split("."))
    except ValueError:
        return (0,)


def _is_version_dir(path: Path) -> bool:
    """True if *path* is a directory whose name looks like a semver string and contains files."""
    if not path.is_dir():
        return False
    parts = path.name.split(".")
    if len(parts) < 2 or not all(p.isdigit() for p in parts):
        return False
    return any(p.is_file() for p in path.rglob("*"))


def _purge_empty_version_dirs(plugins_dir: Path) -> None:
    """Remove version directories that contain no actual files (ghost dirs)."""
    for slug_dir in plugins_dir.iterdir():
        if not slug_dir.is_dir():
            continue
        for child in slug_dir.iterdir():
            if not child.is_dir():
                continue
            parts = child.name.split(".")
            if len(parts) < 2 or not all(p.isdigit() for p in parts):
                continue
            if not any(p.is_file() for p in child.rglob("*")):
                shutil.rmtree(child)
                print(f"  PURGE   {child.relative_to(plugins_dir.parent)}  (empty version directory)")


# ── Existing root manifest (for field fallbacks) ───────────────────────────────

def _load_existing_root() -> Dict[str, Dict[str, Any]]:
    """Return a slug → entry dict from the current root manifest, or {}."""
    if not ROOT_MANIFEST.exists():
        return {}
    try:
        data = json.loads(ROOT_MANIFEST.read_text())
        return {p["slug"]: p for p in data.get("plugins", [])}
    except (json.JSONDecodeError, KeyError):
        return {}


# ── Per-plugin discovery ───────────────────────────────────────────────────────

def _icon_path(slug_dir: Path, slug: str) -> Optional[str]:
    """Return the repo-relative icon path, or None if no icon exists."""
    for name in ICON_PRIORITY:
        if (slug_dir / name).exists():
            return f"plugins/{slug_dir.name}/{name}"
    return None


def _catalog_meta(slug_dir: Path) -> Dict[str, Any]:
    """Read plugins/<slug>/catalog.json if it exists, else return {}."""
    f = slug_dir / "catalog.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError as exc:
        print(f"  WARNING: {f} is invalid JSON — {exc}", file=sys.stderr)
        return {}


def _read_version_manifest(version_dir: Path) -> Optional[Dict[str, Any]]:
    """Read and return the parsed manifest.json inside a version directory."""
    f = version_dir / "manifest.json"
    if not f.exists():
        print(f"  WARNING: missing {f}", file=sys.stderr)
        return None
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError as exc:
        print(f"  WARNING: {f} is invalid JSON — {exc}", file=sys.stderr)
        return None


def _changelog_rel(version_dir: Path, vmeta: Dict[str, Any]) -> Optional[str]:
    """Return the version-relative changelog filename, or None if there is none.

    A manifest may name the file with "changelog"; otherwise the conventional
    CHANGELOG.md is picked up automatically. Either way the file has to exist.
    """
    declared = str(vmeta.get("changelog") or "").strip("/")
    name = declared or CHANGELOG_FILE
    if (version_dir / name).is_file():
        return name
    if declared:
        print(
            f"  WARNING: {version_dir / declared} is declared as the changelog "
            f"but does not exist",
            file=sys.stderr,
        )
    return None


def _build_plugin_entry(
    slug: str,
    slug_dir: Path,
    existing: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build a root-manifest plugin entry for *slug*, or None on failure."""

    # ── Collect and sort version directories ──────────────────────────────────
    version_dirs = sorted(
        [d for d in slug_dir.iterdir() if _is_version_dir(d)],
        key=lambda d: _semver_tuple(d.name),
    )
    if not version_dirs:
        print(f"  SKIP {slug}: no version directories found", file=sys.stderr)
        return None

    # ── Read all version manifests ────────────────────────────────────────────
    versions: List[Dict[str, Any]] = []
    latest_meta: Optional[Dict[str, Any]] = None

    for vdir in version_dirs:
        vmeta = _read_version_manifest(vdir)
        if vmeta is None:
            continue
        entry_version: Dict[str, Any] = {
            "version":           vdir.name,
            "path":              f"plugins/{slug_dir.name}/{vdir.name}",
            "min_pydeck_version": vmeta["min_pydeck_version"] if "min_pydeck_version" in vmeta else DEFAULT_PYDECK,
            "max_pydeck_version": vmeta["max_pydeck_version"] if "max_pydeck_version" in vmeta else DEFAULT_PYDECK,
        }
        # Each version ships only its own changes, so the path belongs on the
        # version rather than the plugin: the marketplace fetches one file per
        # version in the range it is showing and concatenates them.
        changelog_rel = _changelog_rel(vdir, vmeta)
        if changelog_rel:
            entry_version["changelog_path"] = f"{entry_version['path']}/{changelog_rel}"
        versions.append(entry_version)
        latest_meta = vmeta   # last (highest) version wins

    if not versions or latest_meta is None:
        print(f"  SKIP {slug}: no readable version manifests", file=sys.stderr)
        return None

    latest_version = versions[-1]["version"]

    # ── Resolve catalog-only fields ───────────────────────────────────────────
    # Priority: catalog.json > existing root manifest > sensible defaults
    catalog   = _catalog_meta(slug_dir)
    prev_entry = existing.get(slug, {})

    name     = latest_meta.get("name")    or prev_entry.get("name")    or slug
    summary  = (catalog.get("summary")
                or prev_entry.get("summary")
                or latest_meta.get("description", ""))
    author   = latest_meta.get("author")  or prev_entry.get("author")  or "Unknown"
    category = (catalog.get("category")
                or prev_entry.get("category")
                or "utilities")
    compat   = (catalog.get("compatible_pydeck_versions")
                or prev_entry.get("compatible_pydeck_versions")
                or ["1.0"])

    icon = _icon_path(slug_dir, slug) or prev_entry.get("icon_path")
    if icon is None:
        print(f"  WARNING: {slug} has no icon file", file=sys.stderr)
        icon = ""

    licenses = catalog.get("licenses") or prev_entry.get("licenses") or []

    entry: Dict[str, Any] = {
        "name":                     name,
        "slug":                     slug,
        "category":                 category,
        "summary":                  summary,
        "author":                   author,
        "latest":                   latest_version,
        "icon_path":                icon,
        "compatible_pydeck_versions": compat,
        "versions":                 versions,
    }

    # ── Classic marker ────────────────────────────────────────────────────────
    # Only a plugin that declares "pdk": false in its own version manifest is
    # carried through as classic; the key is never derived from the version
    # folder's contents and never written as true. An absent key means PDK,
    # which is what the marketplace assumes (it tags Classic on `pdk === false`).
    if latest_meta.get("pdk") is False:
        entry["pdk"] = False

    # ── Bundled markdown documentation (latest version only) ──────────────────
    # A plugin version may ship a markdown file referenced by "documentation".
    # Surface a repo-relative path so the marketplace UI can fetch & render it,
    # plus the flag that asks PyDeck to pop the doc up right after install.
    doc_rel = latest_meta.get("documentation")
    if doc_rel:
        latest_path = versions[-1]["path"]
        entry["doc_path"] = f"{latest_path}/{str(doc_rel).strip('/')}"
        entry["show_markdown_after_install"] = bool(
            latest_meta.get("show_markdown_after_install", False)
        )

    if licenses:
        entry["licenses"] = licenses
    return entry


# ── Main ───────────────────────────────────────────────────────────────────────

def generate(label: str, root_url: str, output: Path, dry_run: bool) -> None:
    _purge_empty_version_dirs(PLUGINS_DIR)

    existing = _load_existing_root()
    plugins: List[Dict[str, Any]] = []

    slug_dirs = sorted(
        [d for d in PLUGINS_DIR.iterdir() if d.is_dir()],
        key=lambda d: d.name.lower(),
    )

    print(f"Scanning {len(slug_dirs)} plugin director{'y' if len(slug_dirs) == 1 else 'ies'}…")

    for slug_dir in slug_dirs:
        slug = slug_dir.name
        entry = _build_plugin_entry(slug, slug_dir, existing)
        if entry:
            plugins.append(entry)
            versions_str = ", ".join(v["version"] for v in entry["versions"])
            print(f"  ✓ {entry['name']} ({slug})  [{versions_str}]  latest={entry['latest']}")

    # Sort alphabetically by name
    plugins.sort(key=lambda p: p["name"].lower())

    root = {
        "schema_version": SCHEMA_VERSION,
        "label":          label,
        "root_url":       root_url,
        "generated_at":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plugins":        plugins,
    }

    output_text = json.dumps(root, indent=2, ensure_ascii=False) + "\n"

    if dry_run:
        print("\n── dry-run output ──────────────────────────────────────────────")
        print(output_text)
    else:
        output.write_text(output_text)
        print(f"\nWrote {len(plugins)} plugin(s) → {output.relative_to(REPO_ROOT)}")


def main() -> None:
    plugin_hint = default_pydeck_plugin_install_dir()
    parser = argparse.ArgumentParser(
        description=(
            "Generate the root manifest.json for the pydeck-plugins repo.\n\n"
            f"To populate version folders from a running PyDeck, use sync_from_pydeck.py "
            f"(defaults to plugin data dir: {plugin_hint})."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--label",
        default=DEFAULT_LABEL,
        help=f'Catalog label (default: "{DEFAULT_LABEL}")',
    )
    parser.add_argument(
        "--root-url",
        default=default_root_url(),
        help="Base URL the entry paths resolve against "
             "(default: the raw URL of the checked-out branch)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT_MANIFEST,
        help=f"Output path (default: {ROOT_MANIFEST.name})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated JSON to stdout without writing any file",
    )
    args = parser.parse_args()
    generate(label=args.label, root_url=args.root_url,
             output=args.output, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
