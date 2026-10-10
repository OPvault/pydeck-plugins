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
_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8686/oauth/no.pydeck.spotify/callback"

_CREDS_PATH = Path.home() / ".config" / "pydeck" / "core" / "credentials.json"


def _core_store():
    """The core's credential store (PyDeck builds that keep state in pydeck.db).

    ``None`` on an older core, where credentials.json is still the store and
    the file paths below are the fallback.
    """
    try:
        from lib.plugins import credentials_store  # noqa: PLC0415
    except Exception:
        return None
    return credentials_store


class SpotifyError(Exception):
    """A refused request. ``retry_after`` is set when Spotify asked us to wait.

    Spotify answers an over-quota app with 429 and a Retry-After measured in
    *minutes*, so the number has to survive the trip to the caller: a plugin
    that treats it as a transient error and asks again keeps the penalty alive
    for as long as it keeps asking.
    """

    def __init__(self, message: str, retry_after: float | None = None,
                 status: int | None = None, reason: str = ""):
        super().__init__(message)
        self.retry_after = retry_after
        # The HTTP status and Spotify's machine-readable reason, when it gave
        # one -- "NO_ACTIVE_DEVICE" is what a play with nowhere to play says.
        self.status = status
        self.reason = reason

    @property
    def no_active_device(self) -> bool:
        return self.reason == "NO_ACTIVE_DEVICE" or (
            self.status == 404 and not self.reason
        )


class SpotifyClient:
    def __init__(self, client_id: str, client_secret: str,
                 access_token: str = "", refresh_token: str = "",
                 redirect_uri: str = "",
                 creds_key: str = "no.pydeck.spotify"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_expiry: float = 0.0
        self._redirect_uri: str = redirect_uri or _DEFAULT_REDIRECT_URI
        self._creds_key: str = creds_key
        self._lock = threading.Lock()
        # Wall clock, so the window means the same thing in the server and in
        # the listener subprocess that owns the deck.
        self.rate_limited_until: float = 0.0

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
            self.token_expiry = self._expiry_from(data)
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
                self.token_expiry = self._expiry_from(data)
            self._persist_tokens()
            return bool(self.access_token)
        except Exception:
            return False

    @staticmethod
    def _expiry_from(data: dict) -> float:
        try:
            return time.time() + int(data.get("expires_in") or 0)
        except (TypeError, ValueError):
            return 0.0

    def _persist_tokens(self) -> None:
        """Write updated tokens back to the core's credential store."""
        store = _core_store()
        if store is not None:
            try:
                updates = {
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                }
                if self.token_expiry:
                    updates["token_expiry"] = self.token_expiry
                store.update(self._creds_key, updates)
            except Exception:
                pass
            return
        try:
            raw: dict = {}
            if _CREDS_PATH.exists():
                with _CREDS_PATH.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
            creds = raw.setdefault(self._creds_key, {})
            if not isinstance(creds, dict):
                creds = {}
                raw[self._creds_key] = creds
            creds["access_token"] = self.access_token
            creds["refresh_token"] = self.refresh_token
            if self.token_expiry:
                creds["token_expiry"] = self.token_expiry
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
        """Return current playback state, or None if nothing active.

        Raises :class:`SpotifyError` when the request was refused. Swallowing
        that here is what let a rate-limited plugin keep polling: "no playback"
        and "Spotify is refusing you" looked the same to the caller, so nothing
        ever backed off.
        """
        return self._req("GET", "")

    def play(self, device_id: str = "") -> None:
        """Resume on the active device, or on *device_id* when given."""
        self._req("PUT", "/play", query={"device_id": device_id} if device_id else None)

    def devices(self) -> list[dict]:
        """Every Spotify Connect device this account can reach right now.

        A running, logged-in Spotify app stays in this list after a long pause,
        with ``is_active`` false: that is the device a play has to name once
        Spotify has stopped treating anything as the active one.
        """
        data = self._req("GET", "/devices") or {}
        found = data.get("devices") if isinstance(data, dict) else None
        return [d for d in found or [] if isinstance(d, dict) and d.get("id")]

    def transfer(self, device_id: str, play: bool = True) -> None:
        """Move playback to *device_id*, resuming it there when *play* is set."""
        self._req("PUT", "", body={"device_ids": [device_id], "play": bool(play)})

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
        now = time.time()
        if self.rate_limited_until > now:
            raise SpotifyError(
                "Spotify is rate-limiting this app — "
                f"retrying in {int(self.rate_limited_until - now)}s",
                retry_after=self.rate_limited_until - now,
            )
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
            if e.code in (200, 202, 204):
                return {}
            if e.code == 429:
                # A retry here doubles the traffic at the exact moment Spotify
                # is asking for less, and its Retry-After runs to the better
                # part of an hour, so the window is recorded and the request
                # fails. Every caller in this process sees it through
                # rate_limited_until above.
                retry_after = self._retry_after_from(e)
                self.rate_limited_until = max(
                    self.rate_limited_until, time.time() + retry_after
                )
                raise SpotifyError(
                    f"HTTP 429 (Retry-After: {int(retry_after)}s)",
                    retry_after=retry_after,
                )
            # Read Spotify's error body for a useful message
            reason = ""
            try:
                err = json.loads(e.read().decode("utf-8", errors="replace"))
                msg = err.get("error", {}).get("message") or f"HTTP {e.code}"
                reason = str(err.get("error", {}).get("reason") or "")
            except Exception:
                msg = f"HTTP {e.code}"
            raise SpotifyError(msg, status=e.code, reason=reason)
        except urllib.error.URLError as e:
            raise SpotifyError(f"Network error: {e.reason}")

    @staticmethod
    def _retry_after_from(e: urllib.error.HTTPError) -> float:
        """Seconds to wait, from the 429's own header. 60 when it says nothing."""
        raw = e.headers.get("Retry-After") if e.headers else None
        try:
            return max(1.0, float(raw))
        except (TypeError, ValueError):
            return 60.0
