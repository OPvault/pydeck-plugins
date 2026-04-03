"""Browser launch plugin.

Opens URLs in the system default browser.
"""

from __future__ import annotations

import webbrowser
from typing import Any, Dict


def open_url(config: Dict[str, Any]) -> Dict[str, Any]:
    """Open the configured URL in the default browser."""

    url = str(config.get("url") or "https://youtube.com")
    opened = webbrowser.open(url, new=2)
    return {
        "success": bool(opened),
        "url": url,
        "message": "Browser launch attempted",
    }


def open_youtube(config: Dict[str, Any]) -> Dict[str, Any]:
    """Open YouTube in the default browser."""

    data = dict(config or {})
    data.setdefault("url", "https://youtube.com")
    return open_url(data)
