from __future__ import annotations

from pathlib import Path


def write_test_info() -> dict[str, str]:
    return {
        "message": "Postinstall test plugin is installed.",
        "plugin_dir": str(Path(__file__).resolve().parent),
    }
