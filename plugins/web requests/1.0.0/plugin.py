"""HTTP methods plugin for PyDeck.

Sends a request to a configured URL using the selected HTTP method.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Any, Dict, Optional


_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}


def _normalize_method(value: Any) -> str:
    method = str(value or "POST").strip().upper()
    return method if method in _ALLOWED_METHODS else "POST"


def _normalize_url(value: Any) -> str:
    return str(value or "").strip()


def _normalize_body(value: Any) -> str:
    return str(value or "")


def _encode_body(method: str, data: str) -> Optional[bytes]:
    if method in {"GET", "HEAD"}:
        return None
    if not data:
        return None

    return data.encode("utf-8")


def send_request(config: Dict[str, Any]) -> Dict[str, Any]:
    """Send an HTTP request using the configured method and payload."""

    cfg = dict(config or {})
    url = _normalize_url(cfg.get("url"))
    if not url:
        return {
            "success": False,
            "error": "URL is required.",
        }

    method = _normalize_method(cfg.get("method"))
    data = _normalize_body(cfg.get("data"))
    body = _encode_body(method, data)

    headers = {
        "User-Agent": "PyDeck/1.0",
    }

    req = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_body = resp.read().decode("utf-8", errors="replace")
            return {
                "success": True,
                "url": url,
                "method": method,
                "status_code": resp.status,
                "headers": dict(resp.headers.items()),
                "body": response_body,
            }
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        return {
            "success": False,
            "url": url,
            "method": method,
            "status_code": exc.code,
            "error": exc.reason,
            "body": response_body,
        }
    except urllib.error.URLError as exc:
        return {
            "success": False,
            "url": url,
            "method": method,
            "error": str(exc.reason),
        }
