"""RDNN plugin id and function id validation (shared by CLI and TUI)."""

from __future__ import annotations

import re

_FUNC_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Match PyDeck's RDNN rules (see pydeck ``lib/plugin_id.py``).
_RDNN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?)(?:\.[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?){2,}$",
)


def validate_rdnn_plugin_id(plugin_id: str) -> bool:
    s = (plugin_id or "").strip()
    return bool(s) and bool(_RDNN_RE.fullmatch(s))


def validate_plugin_id(raw: str) -> str:
    """Validate and return the RDNN plugin id (install directory name)."""
    s = raw.strip()
    if not validate_rdnn_plugin_id(s):
        raise ValueError(
            "Invalid plugin id: use reverse-DNS form with at least three labels, "
            "e.g. com.example.myplugin or no.pydeck.myplugin "
            "(lowercase letters, digits, hyphen, underscore per label).",
        )
    return s


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
