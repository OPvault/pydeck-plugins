"""
Discord RPC integration using OAuth2 credentials from the Discord Developer Portal.
Connects to the local Discord client via Unix IPC socket to toggle mute/deafen.

Uses a persistent authenticated connection with a background reader thread so that
button presses are instant — no handshake/auth overhead per press.
"""

import json
import os
import queue
import socket
import struct
import threading
import time
import uuid
import urllib.request
import urllib.parse
from pathlib import Path

# OAuth tokens live with other plugin credentials (same file as Spotify, HA, etc.).
_CREDS_PATH = Path.home() / ".config" / "pydeck" / "core" / "credentials.json"
_PLUGIN_KEY = "discord"
# Older PyDeck builds used this file; migrated on first load.
_LEGACY_TOKEN_FILE = Path.home() / ".config" / "pydeck" / "discord_token.json"

_SCOPES = ["rpc", "rpc.voice.read", "rpc.voice.write"]
_TOKEN_URL = "https://discord.com/api/oauth2/token"

# Default matches lib/oauth.py's get_redirect_uri("discord").
# Plugin callers should pass the actual value so it stays in sync with any
# server-port configuration rather than relying on this constant.
_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8686/oauth/discord/callback"

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4


class DiscordRPCError(Exception):
    pass


def _find_ipc_socket() -> str | None:
    def _candidate_dirs(base: str) -> list[str]:
        return [
            base,
            os.path.join(base, "app", "com.discordapp.Discord"),
            os.path.join(base, "app", "com.discordapp.DiscordPTB"),
            os.path.join(base, "app", "com.discordapp.DiscordCanary"),
            os.path.join(base, "snap.discord"),
        ]

    dirs: list[str] = []

    xdg = os.environ.get("XDG_RUNTIME_DIR", "")
    if xdg:
        dirs.extend(_candidate_dirs(xdg))

    # When running as a service (e.g. root), XDG_RUNTIME_DIR may be unset or wrong.
    # Scan every /run/user/<uid>/ directory to find the socket regardless of which
    # user owns the Discord process.
    run_user_root = "/run/user"
    try:
        for entry in os.listdir(run_user_root):
            base = os.path.join(run_user_root, entry)
            if os.path.isdir(base) and base not in dirs:
                dirs.extend(_candidate_dirs(base))
    except OSError:
        pass

    dirs.append("/tmp")

    for d in dirs:
        for i in range(10):
            path = os.path.join(d, f"discord-ipc-{i}")
            if os.path.exists(path):
                return path
    return None


def _pack(opcode: int, payload) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    return struct.pack("<II", opcode, len(data)) + data


def _recv_msg(sock: socket.socket) -> tuple[int, dict]:
    header = b""
    while len(header) < 8:
        chunk = sock.recv(8 - len(header))
        if not chunk:
            raise ConnectionError("Discord IPC disconnected")
        header += chunk
    opcode, length = struct.unpack("<II", header)
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("Discord IPC disconnected")
        data += chunk
    return opcode, json.loads(data)


class DiscordRPC:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        # Falls back to _DEFAULT_REDIRECT_URI when callers don't specify one
        # explicitly.  Plugin code should pass the value from lib.oauth so the
        # URI stays in sync with the server's actual port/path configuration.
        self._redirect_uri: str = redirect_uri or _DEFAULT_REDIRECT_URI
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_expiry: float = 0

        # Persistent connection state
        self._sock: socket.socket | None = None
        self._sock_lock = threading.Lock()
        self._pending: dict[str, queue.Queue] = {}   # nonce -> response queue
        self._pending_lock = threading.Lock()
        self._reader: threading.Thread | None = None

        self._load_tokens()

    # ── Token persistence ──────────────────────────────────────────────────

    def _load_tokens(self):
        if self._load_tokens_from_credentials():
            return
        self._migrate_legacy_token_file()

    def _load_tokens_from_credentials(self) -> bool:
        try:
            if not _CREDS_PATH.is_file():
                return False
            with _CREDS_PATH.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            data = raw.get(_PLUGIN_KEY, {})
            if not isinstance(data, dict) or data.get("client_id") != self.client_id:
                return False
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._token_expiry = float(
                data.get("token_expiry", data.get("expiry", 0)) or 0
            )
            return bool(self._access_token or self._refresh_token)
        except Exception:
            return False

    def _migrate_legacy_token_file(self) -> None:
        if not _LEGACY_TOKEN_FILE.is_file():
            return
        try:
            with _LEGACY_TOKEN_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("client_id") != self.client_id:
                return
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._token_expiry = float(data.get("expiry", data.get("token_expiry", 0)) or 0)
            self._save_tokens()
        except Exception:
            return
        try:
            _LEGACY_TOKEN_FILE.unlink()
        except OSError:
            pass

    def _save_tokens(self):
        try:
            raw: dict = {}
            if _CREDS_PATH.is_file():
                with _CREDS_PATH.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
            if not isinstance(raw, dict):
                raw = {}
            creds = raw.setdefault(_PLUGIN_KEY, {})
            if not isinstance(creds, dict):
                creds = {}
                raw[_PLUGIN_KEY] = creds
            creds["client_id"] = self.client_id
            creds["access_token"] = self._access_token
            creds["refresh_token"] = self._refresh_token
            creds["token_expiry"] = self._token_expiry
            creds.pop("expiry", None)
            _CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _CREDS_PATH.open("w", encoding="utf-8") as f:
                json.dump(raw, f, indent=2)
                f.write("\n")
        except Exception:
            pass

    def clear_tokens(self):
        self._access_token = None
        self._refresh_token = None
        self._token_expiry = 0
        self._disconnect()
        try:
            if _CREDS_PATH.is_file():
                with _CREDS_PATH.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    creds = raw.get(_PLUGIN_KEY, {})
                    if isinstance(creds, dict):
                        for k in ("access_token", "refresh_token", "token_expiry", "expiry"):
                            creds.pop(k, None)
                        raw[_PLUGIN_KEY] = creds
                    with _CREDS_PATH.open("w", encoding="utf-8") as f:
                        json.dump(raw, f, indent=2)
                        f.write("\n")
        except Exception:
            pass
        try:
            if _LEGACY_TOKEN_FILE.is_file():
                _LEGACY_TOKEN_FILE.unlink()
        except OSError:
            pass

    # ── OAuth2 helpers ─────────────────────────────────────────────────────

    def _http_post_form(self, params: dict) -> dict:
        import urllib.error as _uerr
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(
            _TOKEN_URL, data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "DiscordBot (pydeck, 1.0)",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except _uerr.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            try:
                err = json.loads(body)
                raise DiscordRPCError(
                    f"OAuth2 {e.code}: {err.get('error', '?')} — {err.get('error_description', body)}"
                )
            except (json.JSONDecodeError, KeyError):
                raise DiscordRPCError(f"OAuth2 HTTP {e.code}: {body}")

    def _exchange_code(self, code: str):
        result = self._http_post_form({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
        })
        self._access_token = result["access_token"]
        self._refresh_token = result.get("refresh_token")
        self._token_expiry = time.time() + result.get("expires_in", 604800)
        self._save_tokens()

    def _refresh_access_token(self) -> bool:
        if not self._refresh_token:
            return False
        try:
            result = self._http_post_form({
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            })
            self._access_token = result["access_token"]
            self._refresh_token = result.get("refresh_token", self._refresh_token)
            self._token_expiry = time.time() + result.get("expires_in", 604800)
            self._save_tokens()
            return True
        except Exception:
            return False

    # ── Persistent connection ──────────────────────────────────────────────

    def _reader_loop(self, sock: socket.socket):
        """Background thread: reads messages, handles PINGs, delivers responses."""
        try:
            while True:
                op, msg = _recv_msg(sock)
                if op == OP_PING:
                    sock.sendall(_pack(OP_PONG, msg))
                    continue
                if op == OP_CLOSE:
                    break
                nonce = msg.get("nonce")
                if nonce:
                    with self._pending_lock:
                        q = self._pending.get(nonce)
                    if q:
                        q.put(msg)
        except Exception:
            pass
        finally:
            with self._sock_lock:
                if self._sock is sock:
                    self._sock = None
            # Wake up any waiting callers so they can see the connection is gone
            with self._pending_lock:
                for q in self._pending.values():
                    q.put(None)

    def _disconnect(self):
        with self._sock_lock:
            sock = self._sock
            self._sock = None
        if sock:
            try:
                sock.close()
            except Exception:
                pass

    def _connect_and_auth(self):
        """Open IPC socket, handshake, and authenticate. Starts reader thread."""
        if time.time() >= self._token_expiry - 60:
            if not self._refresh_access_token():
                raise DiscordRPCError("Token expired — please re-authorize")

        path = _find_ipc_socket()
        if not path:
            raise DiscordRPCError("Discord IPC socket not found — is Discord running?")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(path)

        # Handshake
        sock.sendall(_pack(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id}))
        op, msg = _recv_msg(sock)
        if op == OP_CLOSE or msg.get("evt") != "READY":
            sock.close()
            raise DiscordRPCError(f"Handshake failed: {msg}")

        # Start reader before sending AUTHENTICATE so no messages are missed
        t = threading.Thread(target=self._reader_loop, args=(sock,), daemon=True)
        t.start()

        # Authenticate
        try:
            resp = self._send_on(sock, "AUTHENTICATE", {"access_token": self._access_token})
        except DiscordRPCError:
            sock.close()
            raise
        if resp is None or resp.get("evt") == "ERROR":
            sock.close()
            # Discard ALL tokens so the next press triggers a full re-authorization
            # rather than looping: refreshing produces a new token that also fails.
            self.clear_tokens()
            err_data = (resp or {}).get("data", {})
            err_msg = err_data.get("message") or err_data.get("code") or str(resp)
            raise DiscordRPCError(f"Authentication failed: {err_msg}")

        with self._sock_lock:
            self._sock = sock
        self._reader = t

    def _send_on(self, sock: socket.socket, cmd: str, args: dict, timeout: float = 15.0) -> dict | None:
        """Send a command on a specific socket and wait for the response."""
        nonce = str(uuid.uuid4())
        q: queue.Queue = queue.Queue()
        with self._pending_lock:
            self._pending[nonce] = q
        try:
            sock.sendall(_pack(OP_FRAME, {"cmd": cmd, "args": args, "nonce": nonce}))
            try:
                msg = q.get(timeout=timeout)
            except queue.Empty:
                raise DiscordRPCError(
                    "Discord IPC timed out — is Discord running and not frozen?"
                )
            return msg
        finally:
            with self._pending_lock:
                self._pending.pop(nonce, None)

    def _ensure_connected(self) -> socket.socket:
        """Return the active authenticated socket, reconnecting if needed."""
        with self._sock_lock:
            sock = self._sock
        if sock is not None:
            return sock
        self._connect_and_auth()
        with self._sock_lock:
            return self._sock

    # ── Public API ─────────────────────────────────────────────────────────

    def is_authorized(self) -> bool:
        if self._access_token and time.time() < self._token_expiry - 60:
            return True
        if self._refresh_token:
            return self._refresh_access_token()
        return False

    def authorize(self):
        """
        Run the OAuth2 AUTHORIZE flow via Discord's in-app dialog.
        Blocks until the user approves or denies.
        """
        path = _find_ipc_socket()
        if not path:
            raise DiscordRPCError("Discord IPC socket not found — is Discord running?")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(path)
        try:
            sock.sendall(_pack(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id}))
            op, msg = _recv_msg(sock)
            if op == OP_CLOSE or msg.get("evt") != "READY":
                raise DiscordRPCError(f"Handshake failed: {msg}")

            # AUTHORIZE blocks until user interacts with Discord — use a long timeout
            nonce = str(uuid.uuid4())
            q: queue.Queue = queue.Queue()
            with self._pending_lock:
                self._pending[nonce] = q

            # Start a temporary reader so we can handle the blocking AUTHORIZE response
            t = threading.Thread(target=self._reader_loop, args=(sock,), daemon=True)
            t.start()

            sock.sendall(_pack(OP_FRAME, {"cmd": "AUTHORIZE", "args": {
                "client_id": self.client_id,
                "scopes": _SCOPES,
            }, "nonce": nonce}))

            resp = q.get(timeout=120)
            with self._pending_lock:
                self._pending.pop(nonce, None)

            if resp is None:
                raise DiscordRPCError("Connection closed while waiting for authorization")
            if resp.get("evt") == "ERROR":
                raise DiscordRPCError(resp["data"].get("message", str(resp)))

            code = resp["data"]["code"]
            self._exchange_code(code)
        finally:
            sock.close()
            # Wait for the temp reader to finish so its cleanup can't corrupt
            # pending queues used by the _connect_and_auth call below.
            t.join(timeout=3)

        # Pre-establish the persistent connection now that we have a token
        try:
            self._connect_and_auth()
        except Exception:
            pass  # Will reconnect on first use

    def get_voice_settings(self) -> dict:
        """Return the current voice settings as {"mute": bool, "deaf": bool}."""
        sock = self._ensure_connected()
        try:
            resp = self._send_on(sock, "GET_VOICE_SETTINGS", {})
            if resp is None:
                raise DiscordRPCError("Lost connection to Discord")
        except DiscordRPCError:
            self._disconnect()
            raise
        data = resp.get("data", {})
        return {"mute": bool(data.get("mute", False)), "deaf": bool(data.get("deaf", False))}

    def toggle_mute(self) -> dict:
        """Toggle mute and return the confirmed voice settings {"mute": bool, "deaf": bool}."""
        sock = self._ensure_connected()
        try:
            resp = self._send_on(sock, "GET_VOICE_SETTINGS", {})
            if resp is None:
                raise DiscordRPCError("Lost connection to Discord")
            muted = resp["data"].get("mute", False)
            deafened = resp["data"].get("deaf", False)
            # When deafened, Discord treats the mute button as "undeafen" — mimic
            # that behaviour so the button clears both states and updates both icons.
            if deafened:
                set_resp = self._send_on(sock, "SET_VOICE_SETTINGS", {"deaf": False})
            else:
                set_resp = self._send_on(sock, "SET_VOICE_SETTINGS", {"mute": not muted})
        except DiscordRPCError:
            self._disconnect()
            raise
        # SET_VOICE_SETTINGS returns the full updated settings in data
        confirmed = (set_resp or {}).get("data", resp["data"])
        return {"mute": bool(confirmed.get("mute", not muted)), "deaf": bool(confirmed.get("deaf", False))}

    def toggle_deafen(self) -> dict:
        """Toggle deafen and return the confirmed voice settings {"mute": bool, "deaf": bool}."""
        sock = self._ensure_connected()
        try:
            resp = self._send_on(sock, "GET_VOICE_SETTINGS", {})
            if resp is None:
                raise DiscordRPCError("Lost connection to Discord")
            deafened = resp["data"].get("deaf", False)
            set_resp = self._send_on(sock, "SET_VOICE_SETTINGS", {"deaf": not deafened})
        except DiscordRPCError:
            self._disconnect()
            raise
        confirmed = (set_resp or {}).get("data", resp["data"])
        return {"mute": bool(confirmed.get("mute", False)), "deaf": bool(confirmed.get("deaf", not deafened))}
