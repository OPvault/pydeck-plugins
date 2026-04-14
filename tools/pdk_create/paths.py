"""Resolve pydeck ``plugins/plugin/`` directory — same rules as sync_from_pydeck / generate_manifest context.

``sync_from_pydeck.py`` stores ``pydeck_source`` in:

    ~/.config/pydeck/pydeck-plugins/path.json

That path points at **plugins/plugin** (the directory that contains plugin slug folders),
not the pydeck repository root.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

# pydeck-plugins repository root (parent of tools/)
REPO_ROOT = Path(__file__).resolve().parents[2]

# Same as sync_from_pydeck.CONFIG_PATH
CONFIG_PATH = Path.home() / ".config" / "pydeck" / "pydeck-plugins" / "path.json"

# Same order as sync_from_pydeck._CANDIDATES (paths to plugins/plugin)
_CANDIDATES: list[Path] = [
    Path.home() / "Documents" / "GitHub" / "pydeck" / "plugins" / "plugin",
    REPO_ROOT.parent / "pydeck" / "plugins" / "plugin",
    Path.home() / "pydeck" / "plugins" / "plugin",
]


def load_saved_plugin_parent() -> Optional[Path]:
    """Return saved ``plugins/plugin`` path from path.json, or None."""
    if not CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        raw = data.get("pydeck_source", "")
        if not raw:
            return None
        p = Path(raw).expanduser().resolve()
        return p if p.is_dir() else None
    except (json.JSONDecodeError, OSError):
        return None


def first_existing_candidate() -> Optional[Path]:
    """Return the first candidate directory that exists (same heuristic as sync)."""
    for candidate in _CANDIDATES:
        if candidate.is_dir():
            return candidate
    return None


def validate_plugin_parent(path: Path) -> Path:
    """Ensure *path* is an existing directory (the plugins/plugin folder)."""
    p = path.expanduser().resolve()
    if not p.is_dir():
        raise FileNotFoundError(f"Not a directory: {p}")
    return p


def resolve_plugin_parent(
    pydeck_source: Optional[str],
    pydeck_root: Optional[str],
) -> Optional[Path]:
    """Resolve the ``plugins/plugin`` directory without prompting.

    Precedence (same spirit as ``sync_from_pydeck._resolve_source`` override handling):

    1. ``--pydeck-source`` (path to ``plugins/plugin``)
    2. ``--pydeck-root`` (pydeck repo root → ``<root>/plugins/plugin``)
    3. Environment ``PYDECK_SOURCE`` (path to ``plugins/plugin``)
    4. Environment ``PYDECK_ROOT`` (repo root → ``<root>/plugins/plugin``)
    5. Saved ``path.json`` → ``pydeck_source``
    6. First existing entry in ``_CANDIDATES``

    Returns None if nothing is configured and no candidate exists — caller should prompt.
    """
    if pydeck_source:
        return validate_plugin_parent(Path(pydeck_source))

    if pydeck_root:
        root = Path(pydeck_root).expanduser().resolve()
        return validate_plugin_parent(root / "plugins" / "plugin")

    env_src = os.environ.get("PYDECK_SOURCE", "").strip()
    if env_src:
        return validate_plugin_parent(Path(env_src))

    env_root = os.environ.get("PYDECK_ROOT", "").strip()
    if env_root:
        return validate_plugin_parent(Path(env_root).expanduser().resolve() / "plugins" / "plugin")

    saved = load_saved_plugin_parent()
    if saved is not None:
        return saved

    detected = first_existing_candidate()
    if detected is not None:
        return detected

    return None


def prompt_for_plugin_parent(detected: Optional[Path]) -> Path:
    """Ask for ``plugins/plugin`` path (interactive), same prompts as sync first-run."""
    if detected is not None:
        print("\nDetected pydeck plugins directory:")
        print(f"  {detected}")
        answer = input("Is this correct? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            return detected

    if detected is None:
        print("Could not auto-detect pydeck's plugins/plugin/ directory.")

    while True:
        raw = input(
            "Enter the full path to pydeck's plugins/plugin/ directory: ",
        ).strip()
        p = Path(raw).expanduser().resolve()
        if p.is_dir():
            return p
        print(f"  Path not found: {p}. Try again.")
