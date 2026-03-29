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

DISCORD_TOKEN_FILE = os.path.join(
    os.path.expanduser("~"), ".config", "pydeck", "discord_token.json"
)

_SCOPES = ["rpc", "rpc.voice.read", "rpc.voice.write"]
_TOKEN_URL = "https://discord.com/api/oauth2/token"
_REDIRECT_URI = "http://localhost"

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
    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
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
        try:
            with open(DISCORD_TOKEN_FILE) as f:
                data = json.load(f)
            if data.get("client_id") == self.client_id:
                self._access_token = data.get("access_token")
                self._refresh_token = data.get("refresh_token")
                self._token_expiry = data.get("expiry", 0)
        except Exception:
            pass

    def _save_tokens(self):
        os.makedirs(os.path.dirname(DISCORD_TOKEN_FILE), exist_ok=True)
        with open(DISCORD_TOKEN_FILE, "w") as f:
            json.dump({
                "client_id": self.client_id,
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "expiry": self._token_expiry,
            }, f)

    def clear_tokens(self):
        self._access_token = None
        self._refresh_token = None
        self._token_expiry = 0
        self._disconnect()
        try:
            os.remove(DISCORD_TOKEN_FILE)
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
            "redirect_uri": _REDIRECT_URI,
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
        resp = self._send_on(sock, "AUTHENTICATE", {"access_token": self._access_token})
        if resp is None or resp.get("evt") == "ERROR":
            sock.close()
            raise DiscordRPCError(f"Authentication failed: {resp}")

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
            msg = q.get(timeout=timeout)
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

        # Pre-establish the persistent connection now that we have a token
        try:
            self._connect_and_auth()
        except Exception:
            pass  # Will reconnect on first use

    def get_voice_settings(self) -> dict:
        """Return the current voice settings as {"mute": bool, "deaf": bool}."""
        sock = self._ensure_connected()
        resp = self._send_on(sock, "GET_VOICE_SETTINGS", {})
        if resp is None:
            self._disconnect()
            raise DiscordRPCError("Lost connection to Discord")
        data = resp.get("data", {})
        return {"mute": bool(data.get("mute", False)), "deaf": bool(data.get("deaf", False))}

    def toggle_mute(self) -> dict:
        """Toggle mute and return the confirmed voice settings {"mute": bool, "deaf": bool}."""
        sock = self._ensure_connected()
        resp = self._send_on(sock, "GET_VOICE_SETTINGS", {})
        if resp is None:
            self._disconnect()
            raise DiscordRPCError("Lost connection to Discord")
        muted = resp["data"].get("mute", False)
        set_resp = self._send_on(sock, "SET_VOICE_SETTINGS", {"mute": not muted})
        # SET_VOICE_SETTINGS returns the full updated settings in data
        confirmed = (set_resp or {}).get("data", resp["data"])
        return {"mute": bool(confirmed.get("mute", not muted)), "deaf": bool(confirmed.get("deaf", False))}

    def toggle_deafen(self) -> dict:
        """Toggle deafen and return the confirmed voice settings {"mute": bool, "deaf": bool}."""
        sock = self._ensure_connected()
        resp = self._send_on(sock, "GET_VOICE_SETTINGS", {})
        if resp is None:
            self._disconnect()
            raise DiscordRPCError("Lost connection to Discord")
        deafened = resp["data"].get("deaf", False)
        set_resp = self._send_on(sock, "SET_VOICE_SETTINGS", {"deaf": not deafened})
        confirmed = (set_resp or {}).get("data", resp["data"])
        return {"mute": bool(confirmed.get("mute", False)), "deaf": bool(confirmed.get("deaf", not deafened))}
