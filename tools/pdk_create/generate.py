"""Write a PDK new-layout plugin tree under plugins/plugin/<rdnn-plugin-id>/."""

from __future__ import annotations

import html
import json
import shutil
import stat
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List, Literal

Preset = Literal["counter", "static"]


@dataclass
class PluginSpec:
    """Inputs for scaffolding."""

    slug: str  # RDNN plugin id (install directory name)
    name: str
    description: str
    author: str
    version: str
    functions: List[str]
    preset: Preset
    min_pydeck_version: str = "2.0.0"
    include_post_install_script: bool = False


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _chmod_exec(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def _manifest_json(spec: PluginSpec) -> dict:
    functions: dict = {}
    for fn in spec.functions:
        label = fn.replace("_", " ").title()
        entry: dict = {
            "label": label,
            "description": f"{spec.description} ({fn})",
            "title_readonly": True,
            "disableGallary": True,
            "disableGallery": True,
            "default_display": {
                "color": "#1a1a2e",
                "text": label[:12],
                "text_position": "bottom",
                "scroll_enabled": False,
            },
            "ui": [],
        }
        functions[fn] = entry

    manifest: dict = {
        "name": spec.name,
        "version": spec.version,
        "description": spec.description,
        "author": spec.author,
        "min_pydeck_version": spec.min_pydeck_version,
        "max_pydeck_version": None,
        "changelog": "CHANGELOG.md",
        "functions": functions,
    }
    if spec.include_post_install_script:
        manifest["post_install_script"] = "scripts/setup.sh"
    return manifest


def _shared_py(spec: PluginSpec) -> str:
    return f'''"""PDK plugin {spec.slug} — shared utilities.

Per-function handlers live under src/functions/<name>/handler.py
"""

from __future__ import annotations

# Add shared helpers imported by handlers here.
'''


def _shared_css() -> str:
    return """:root {
  --bg: {_button_color};
  --fg: #ffffff;
}

.face {
  background: var(--bg);
  padding: 6;
  direction: column;
  align: center;
  justify: center;
  gap: 4;
}

.label {
  color: var(--fg);
  font-size: 0.65em;
  text-align: center;
}

.count {
  color: var(--fg);
  font-size: 1.4em;
  font-weight: bold;
  text-align: center;
}
"""


def _func_style_css() -> str:
    return """/* Per-function overrides (optional) */
"""


def _plugin_settings_json() -> str:
    """A small plugin-settings.json the scaffolded handlers read.

    Plugin settings are plugin-wide: the user sets them once under Settings ->
    Plugin settings and every handler reads them as ``ctx.settings``. Two
    fields are enough to show the shape; the full field reference is the
    "Plugin settings" page of the docs.
    """
    data = {
        "save_button": False,
        "fields": [
            {
                "type": "input",
                "id": "label_text",
                "label": "Button label",
                "default": "",
                "placeholder": "Leave empty to use the function name",
                "description": "Shown on every button of this plugin.",
            },
            {
                "type": "checkbox",
                "id": "uppercase",
                "label": "Show the label in capitals",
                "default": False,
            },
        ],
    }
    return json.dumps(data, indent=2) + "\n"


def _label_helper(title: str) -> str:
    return f'''

def _label(ctx: Any) -> str:
    """The face's label, from the plugin-wide settings (plugin-settings.json).

    ``getattr``: a PyDeck from before plugin settings has no ``ctx.settings``.
    """
    settings = getattr(ctx, "settings", None) or {{}}
    text = str(settings.get("label_text") or "").strip() or "{title}"
    return text.upper() if settings.get("uppercase") else text
'''


def _handler_py(spec: PluginSpec, func: str) -> str:
    title = func.replace("_", " ").title()
    if spec.preset == "counter":
        return f'''"""PDK handler for `{func}`."""

from __future__ import annotations

from typing import Any
{_label_helper(title)}

def on_load(ctx: Any) -> None:
    ctx.state._template = "{func}"
    ctx.state.label = _label(ctx)
    ctx.state.count = 0


def on_press(ctx: Any) -> None:
    ctx.state.count = int(ctx.state.get("count") or 0) + 1


def on_poll(ctx: Any, interval: int = 1000) -> None:
    """Keep the face in sync; PyDeck also polls right after a settings change."""
    ctx.state.label = _label(ctx)
'''
    return f'''"""PDK handler for `{func}`."""

from __future__ import annotations

from typing import Any
{_label_helper(title)}

def on_load(ctx: Any) -> None:
    ctx.state._template = "{func}"
    ctx.state.label = _label(ctx)


def on_press(ctx: Any) -> None:
    pass


def on_poll(ctx: Any, interval: int = 1000) -> None:
    """PyDeck polls right after a settings change, so the label follows it."""
    ctx.state.label = _label(ctx)
'''


def _template_xml(spec: PluginSpec, func: str) -> str:
    title = html.escape(func.replace("_", " ").title(), quote=True)
    desc = html.escape(f"{spec.description} ({func})", quote=True)
    if spec.preset == "counter":
        return f'''<template name="{func}" title="{title}" description="{desc}">
  <box class="face">
    <text class="label">{{label}}</text>
    <text class="count">{{count}}</text>
  </box>
</template>
'''
    return f'''<template name="{func}" title="{title}" description="{desc}">
  <box class="face">
    <text class="label">{{label}}</text>
  </box>
</template>
'''


def _options_json(spec: PluginSpec) -> str:
    data = {
        "description": spec.description,
        "features": [],
        "tags": ["pdk"],
    }
    return json.dumps(data, indent=2) + "\n"


def _changelog_md(spec: PluginSpec) -> str:
    """One section covering this version only — PyDeck joins versions itself."""
    return f"""## {spec.version} — {date.today().isoformat()}

- Initial release.
"""


def _license_main(spec: PluginSpec) -> str:
    return f"""License placeholder for {spec.name}

Replace this file with your plugin's license text (e.g. MIT).
Copyright (c) {spec.author}
"""


def _setup_sh(spec: PluginSpec) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
# Post-install hook for marketplace installs (optional).
echo "Post-install placeholder for plugin: {spec.slug}"
exit 0
"""


def write_plugin(
    plugin_root: Path,
    spec: PluginSpec,
    *,
    force: bool = False,
) -> None:
    """Write the full tree to *plugin_root* (plugins/plugin/<rdnn-id>)."""
    if plugin_root.exists():
        if not plugin_root.is_dir():
            raise NotADirectoryError(f"Not a directory: {plugin_root}")
        if any(plugin_root.iterdir()):
            if not force:
                raise FileExistsError(
                    f"Target is not empty: {plugin_root}. Use --force to overwrite.",
                )
            shutil.rmtree(plugin_root)

    # Directories
    (plugin_root / "src" / "functions").mkdir(parents=True, exist_ok=True)
    (plugin_root / "assets" / "icons").mkdir(parents=True, exist_ok=True)
    (plugin_root / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
    if spec.include_post_install_script:
        (plugin_root / "scripts").mkdir(parents=True, exist_ok=True)
    (plugin_root / "meta" / "licenses").mkdir(parents=True, exist_ok=True)

    _write_text(plugin_root / "manifest.json", json.dumps(_manifest_json(spec), indent=2) + "\n")
    _write_text(plugin_root / "CHANGELOG.md", _changelog_md(spec))
    _write_text(plugin_root / "plugin-settings.json", _plugin_settings_json())
    _write_text(plugin_root / "src" / "shared.py", _shared_py(spec))
    _write_text(plugin_root / "src" / "shared.css", _shared_css())

    for fn in spec.functions:
        base = plugin_root / "src" / "functions" / fn
        _write_text(base / "template.xml", _template_xml(spec, fn))
        _write_text(base / "handler.py", _handler_py(spec, fn))
        _write_text(base / "style.css", _func_style_css())

    _write_text(plugin_root / "assets" / "icons" / ".gitkeep", "")
    _write_text(plugin_root / "assets" / "fonts" / ".gitkeep", "")

    if spec.include_post_install_script:
        setup = plugin_root / "scripts" / "setup.sh"
        _write_text(setup, _setup_sh(spec))
        _chmod_exec(setup)

    _write_text(plugin_root / "meta" / "options.json", _options_json(spec))
    _write_text(plugin_root / "meta" / "licenses" / "LICENSE-main", _license_main(spec))
