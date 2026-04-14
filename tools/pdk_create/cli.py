"""CLI for scaffolding a PyDeck PDK plugin into a pydev checkout."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .generate import PluginSpec, write_plugin
from .paths import (
    CONFIG_PATH,
    first_existing_candidate,
    prompt_for_plugin_parent,
    resolve_plugin_parent,
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_FUNC_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not _SLUG_RE.match(slug):
        raise ValueError(
            "Invalid slug: use lowercase letters, digits, underscores, hyphens "
            "(must start with a letter or digit).",
        )
    return slug


def validate_functions(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    if not parts:
        raise ValueError("At least one function id is required.")
    out: list[str] = []
    for p in parts:
        if not _FUNC_RE.match(p):
            raise ValueError(
                f"Invalid function id {p!r}: use snake_case (letter first, then "
                "letters, digits, underscores).",
            )
        out.append(p)
    return out


def interactive_defaults() -> dict:
    print("PyDeck PDK plugin creator — interactive scaffold\n")
    slug = ""
    while True:
        slug = input("Plugin slug (folder name) [my_plugin]: ").strip() or "my_plugin"
        try:
            slug = validate_slug(slug)
            break
        except ValueError as e:
            _err(str(e))
    name = input("Display name [My Plugin]: ").strip() or "My Plugin"
    desc = input("Description [PDK demo plugin]: ").strip() or "PDK demo plugin"
    author = input("Author [You]: ").strip() or "You"
    version = input("Version [0.1.0]: ").strip() or "0.1.0"
    functions_raw = input(
        "Function ids (comma-separated) [main]: ",
    ).strip() or "main"
    functions = validate_functions(functions_raw)
    preset_in = input("Preset: counter | static [static]: ").strip().lower() or "static"
    if preset_in not in ("counter", "static"):
        _err("Unknown preset; using static.")
        preset_in = "static"
    min_pv = input("min_pydeck_version [1.1.0]: ").strip() or "1.1.0"
    return {
        "slug": slug,
        "name": name,
        "description": desc,
        "author": author,
        "version": version,
        "functions": functions,
        "preset": preset_in,
        "min_pydeck_version": min_pv,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Create a PyDeck PDK plugin under plugins/plugin/<slug>/ "
        "inside a pydeck checkout. Resolves the plugins/plugin directory the "
        "same way as sync_from_pydeck.py (path.json, candidates, PYDECK_SOURCE).",
    )
    p.add_argument(
        "--pydeck-source",
        metavar="PATH",
        help="Path to pydeck's plugins/plugin/ directory (same as sync_from_pydeck --pydeck-source)",
    )
    p.add_argument(
        "--pydeck-root",
        metavar="PATH",
        help="PyDeck repository root (uses <root>/plugins/plugin/). "
        "Ignored if --pydeck-source is set.",
    )
    p.add_argument(
        "--slug",
        help="Plugin directory name (lowercase, a-z0-9_-)",
    )
    p.add_argument(
        "--name",
        help="Display name in manifest.json",
    )
    p.add_argument(
        "--description",
        default="PDK demo plugin",
        help="Short description",
    )
    p.add_argument(
        "--author",
        default="You",
        help="Author string",
    )
    p.add_argument(
        "--version",
        default="0.1.0",
        help="Semantic version",
    )
    p.add_argument(
        "--functions",
        metavar="LIST",
        help="Comma-separated function ids (snake_case), e.g. main,action_two",
    )
    p.add_argument(
        "--preset",
        choices=("counter", "static"),
        default="static",
        help="counter: press increments a number; static: label only",
    )
    p.add_argument(
        "--min-pydeck-version",
        default="1.1.0",
        dest="min_pydeck_version",
        help="Written to manifest.json",
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt; requires resolvable plugins path (see --pydeck-source)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite non-empty plugin directory",
    )
    return p


def _resolve_plugins_dir(
    args: argparse.Namespace,
    *,
    interactive: bool,
) -> Path:
    """Return the directory that contains plugin slug folders (plugins/plugin)."""
    try:
        resolved = resolve_plugin_parent(
            args.pydeck_source,
            args.pydeck_root,
        )
    except FileNotFoundError as e:
        raise FileNotFoundError(str(e)) from e

    if resolved is not None:
        return resolved

    if interactive:
        print(
            "\nNo plugins directory from env, config, or candidates.\n"
            f"  Config file (optional): {CONFIG_PATH}\n"
            "  (same file as sync_from_pydeck.py: key pydeck_source)\n",
        )
        return prompt_for_plugin_parent(first_existing_candidate())

    raise FileNotFoundError(
        "Could not resolve pydeck plugins/plugin directory. Set one of:\n"
        "  --pydeck-source PATH   path to plugins/plugin/\n"
        "  --pydeck-root PATH     pydeck repo root\n"
        "  PYDECK_SOURCE          path to plugins/plugin/\n"
        "  PYDECK_ROOT            pydeck repo root\n"
        f"  Or create {CONFIG_PATH} with {{\"pydeck_source\": \"...\"}} (see sync_from_pydeck.py).",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.non_interactive:
        if not args.slug or not args.name:
            _err("--non-interactive requires --slug and --name.")
            return 2
        try:
            slug = validate_slug(args.slug)
            functions = validate_functions(
                args.functions or "main",
            )
        except ValueError as e:
            _err(str(e))
            return 2
        try:
            plugins_dir = _resolve_plugins_dir(args, interactive=False)
        except FileNotFoundError as e:
            _err(str(e))
            return 2
        spec = PluginSpec(
            slug=slug,
            name=args.name,
            description=args.description,
            author=args.author,
            version=args.version,
            functions=functions,
            preset=args.preset,
            min_pydeck_version=args.min_pydeck_version,
        )
        plugin_root = plugins_dir / spec.slug
    else:
        data = interactive_defaults()
        try:
            slug = validate_slug(data["slug"])
            functions = data["functions"]
        except ValueError as e:
            _err(str(e))
            return 2
        try:
            plugins_dir = _resolve_plugins_dir(args, interactive=True)
        except FileNotFoundError as e:
            _err(str(e))
            return 2
        preset = data["preset"]
        if preset not in ("counter", "static"):
            preset = "static"
        spec = PluginSpec(
            slug=slug,
            name=data["name"],
            description=data["description"],
            author=data["author"],
            version=data["version"],
            functions=functions,
            preset=preset,
            min_pydeck_version=data["min_pydeck_version"],
        )
        plugin_root = plugins_dir / spec.slug
        if plugin_root.exists() and any(plugin_root.iterdir()):
            yn = input(
                f"{plugin_root} exists and is not empty. Overwrite? [y/N]: ",
            ).strip().lower()
            if yn not in ("y", "yes"):
                print("Aborted.")
                return 1
            args.force = True

    try:
        write_plugin(plugin_root, spec, force=args.force)
    except (FileExistsError, NotADirectoryError) as e:
        _err(str(e))
        return 1

    print(f"Created PDK plugin at:\n  {plugin_root}\n")
    print("Next: restart PyDeck and find the plugin in the sidebar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
