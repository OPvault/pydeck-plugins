"""Shared result type for interactive plugin creation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .generate import PluginSpec


@dataclass(frozen=True)
class InteractiveOutcome:
    """Result of the interactive wizard (TUI or stdin fallback)."""

    plugins_dir: Path
    spec: PluginSpec
    force: bool
