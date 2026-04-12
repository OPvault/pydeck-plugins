"""Spotify Web API client for the PyDeck plugin system.

Implements the Authorization Code OAuth2 flow with automatic token refresh.
Tokens are persisted back to ~/.config/pydeck/core/credentials.json after each refresh
so they survive server restarts without re-authorization.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://accounts.spotify.com/api/token"
AUTH_URL = "https://accounts.spotify.com/authorize"
API_BASE = "https://api.spotify.com/v1/me/player"
SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)
# Fallback used when no redirect_uri is supplied to SpotifyClient.
# Plugin callers should pass the value from lib.oauth.get_redirect_uri so the
# URI stays in sync with any server-port configuration.
_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8686/oauth/spotify/callback"

_CREDS_PATH = Path.home() / ".config" / "pydeck" / "core" / "credentials.json"


class SpotifyError(Exception):
    pass


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str,
                 access_token: str = "", refresh_token: str = "",
                 redirect_uri: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        # Falls back to _DEFAULT_REDIRECT_URI when callers don't specify one.
        # Plugin code should pass the value from lib.oauth so the URI stays in
        # sync with the server's actual port/path configuration.
        self._redirect_uri: str = redirect_uri or _DEFAULT_REDIRECT_URI
        self._lock = threading.Lock()

    def auth_url(self) -> str:
        params = urllib.parse.urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self._redirect_uri,
            "scope": SCOPES,
        })
        return f"{AUTH_URL}?{params}"

    def exchange_code(self, code: str) -> None:
        """Exchange an authorization code for access + refresh tokens."""
        body = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
        }).encode()
        data = self._token_request(body)
        with self._lock:
            self.access_token = data.get("access_token", "")
            self.refresh_token = data.get("refresh_token", "")
        self._persist_tokens()

    def refresh(self) -> bool:
        """Obtain a new access_token via the refresh_token. Returns True on success."""
        if not self.refresh_token:
            return False
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }).encode()
        try:
            data = self._token_request(body)
            with self._lock:
                self.access_token = data.get("access_token", "")
                if data.get("refresh_token"):
                    self.refresh_token = data["refresh_token"]
            self._persist_tokens()
            return bool(self.access_token)
        except Exception:
            return False

    def _persist_tokens(self) -> None:
        """Write updated tokens back to credentials.json."""
        try:
            raw: dict = {}
            if _CREDS_PATH.exists():
                with _CREDS_PATH.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
            creds = raw.setdefault("spotify", {})
            creds["access_token"] = self.access_token
            creds["refresh_token"] = self.refresh_token
            _CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _CREDS_PATH.open("w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2)
                f.write("\n")
        except Exception:
            pass

    def _token_request(self, body: bytes) -> dict:
        cred_str = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        req = urllib.request.Request(
            TOKEN_URL,
            data=body,
            headers={
                "Authorization": f"Basic {cred_str}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    # ── Player controls ───────────────────────────────────────────────────────

    def get_playback(self) -> dict | None:
        """Return current playback state, or None if nothing active."""
        try:
            return self._req("GET", "")
        except SpotifyError:
            return None
        except Exception:
            return None

    def play(self) -> None:
        self._req("PUT", "/play")

    def pause(self) -> None:
        self._req("PUT", "/pause")

    def next_track(self) -> None:
        self._req("POST", "/next")

    def prev_track(self) -> None:
        self._req("POST", "/previous")

    def set_volume(self, percent: int) -> None:
        self._req("PUT", "/volume",
                  query={"volume_percent": max(0, min(100, int(percent)))})

    def set_shuffle(self, state: bool) -> None:
        self._req("PUT", "/shuffle",
                  query={"state": "true" if state else "false"})

    def set_repeat(self, state: str) -> None:
        """state: 'off' | 'context' | 'track'"""
        self._req("PUT", "/repeat", query={"state": state})

    # ── Internal ─────────────────────────────────────────────────────────────

    def _req(self, method: str, path: str,
             query: dict | None = None, body: dict | None = None,
             _retry: bool = True):
        if not self.access_token:
            raise SpotifyError(
                "Not authorized — press the Spotify Authorize button first"
            )
        url = API_BASE + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "User-Agent": "PyDeck/1.0",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                if not raw or not raw.strip():
                    return {}
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    return {}
        except urllib.error.HTTPError as e:
            if e.code == 401 and _retry:
                if self.refresh():
                    return self._req(method, path, query, body, _retry=False)
            if e.code == 429 and _retry:
                retry_after_raw = e.headers.get("Retry-After") if e.headers else None
                try:
                    retry_after = max(0.0, float(retry_after_raw)) if retry_after_raw is not None else 1.0
                except (TypeError, ValueError):
                    retry_after = 1.0
                # Keep retry bounded so button presses do not hang for long.
                time.sleep(min(retry_after, 2.0))
                return self._req(method, path, query, body, _retry=False)
            if e.code in (200, 202, 204):
                return {}
            # Read Spotify's error body for a useful message
            try:
                err = json.loads(e.read().decode("utf-8", errors="replace"))
                msg = err.get("error", {}).get("message") or f"HTTP {e.code}"
            except Exception:
                msg = f"HTTP {e.code}"
            if e.code == 429:
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra:
                    msg = f"HTTP 429 (Retry-After: {ra}s)"
            raise SpotifyError(msg)
        except urllib.error.URLError as e:
            raise SpotifyError(f"Network error: {e.reason}")
