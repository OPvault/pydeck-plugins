"""
Discord RPC integration using OAuth2 credentials from the Discord Developer Portal.
Connects to the local Discord client over its IPC endpoint — a Unix domain socket
on Linux and macOS, a named pipe on Windows — to toggle mute/deafen.

Uses a persistent authenticated connection so that button presses are instant —
no handshake/auth overhead per press.
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

_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.PeekNamedPipe.restype = wintypes.BOOL

# OAuth tokens live with the other plugin credentials, in the core's store.
# The file is the fallback for cores that still keep credentials.json.
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
# The core writes tokens under the RDNN id; the pre-RDNN install used the short
# slug. Read both (RDNN wins) and always write back to the RDNN key.
_PLUGIN_KEY = "no.pydeck.discord"
_LEGACY_PLUGIN_KEY = "discord"
# Older PyDeck builds used this file; migrated on first load.
_LEGACY_TOKEN_FILE = Path.home() / ".config" / "pydeck" / "discord_token.json"

_SCOPES = ["rpc", "rpc.voice.read", "rpc.voice.write"]
_TOKEN_URL = "https://discord.com/api/oauth2/token"

# Default matches lib/oauth.py's get_redirect_uri("no.pydeck.discord").
# Plugin callers should pass the actual value so it stays in sync with any
# server-port configuration rather than relying on this constant.
_DEFAULT_REDIRECT_URI = "http://127.0.0.1:8686/oauth/no.pydeck.discord/callback"

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4

# Discord answers a command in milliseconds but can sit on the handshake and
# AUTHENTICATE for far longer on a cold client, so opening a connection gets a
# budget of its own rather than the per-command one.
_CONNECT_TIMEOUT = 60.0


class DiscordRPCError(Exception):
    pass


def _unix_socket_paths() -> list[str]:
    """Every plausible discord-ipc-N Unix socket, in the order to try them."""

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

    # macOS puts it in the per-user temp dir; /tmp is the last resort everywhere.
    tmpdir = os.environ.get("TMPDIR", "")
    if tmpdir and tmpdir not in dirs:
        dirs.extend(_candidate_dirs(tmpdir))
    dirs.append("/tmp")

    paths: list[str] = []
    for d in dirs:
        for i in range(10):
            path = os.path.join(d, f"discord-ipc-{i}")
            if os.path.exists(path):
                paths.append(path)
    return paths


def _windows_pipe_paths() -> list[str]:
    """Every discord-ipc-N named pipe, unfiltered.

    A named pipe has no directory entry to stat — os.path.exists() on one opens
    an instance rather than answering a question — so the candidates are handed
    back as-is and _connect_ipc() finds the live one by trying to open each.
    """
    return [os.path.join(r"\\.\pipe", f"discord-ipc-{i}") for i in range(10)]


def _pack(opcode: int, payload) -> bytes:
    data = json.dumps(payload).encode("utf-8")
    return struct.pack("<II", opcode, len(data)) + data


def _read_frame(read_exact) -> tuple[int, dict]:
    """Read one length-prefixed IPC frame using *read_exact(n) -> bytes*."""
    opcode, length = struct.unpack("<II", read_exact(8))
    data = read_exact(length) if length else b"{}"
    return opcode, json.loads(data)


class _Conn:
    """A live IPC connection to the local Discord client.

    The two transports differ in more than the address. A Unix socket can be
    read by a background thread while another thread writes, so one reader owns
    every recv and hands responses to callers by nonce. A Windows named pipe
    opened by ``open()`` is a *synchronous* handle, and the kernel serialises
    I/O on those: a reader parked in read() blocks the next write outright, for
    as long as Discord stays quiet. So there the caller drives its own round
    trip under a lock instead, and PeekNamedPipe supplies the timeout that a
    blocking read cannot.
    """

    def send(self, opcode: int, payload: dict) -> None:
        raise NotImplementedError

    def read_frame(self, timeout: float = 15.0) -> tuple[int, dict]:
        raise NotImplementedError

    def start(self) -> None:
        """Begin normal operation, once the handshake frame has been read."""

    def request(self, cmd: str, args: dict, timeout: float = 15.0) -> dict | None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    @property
    def alive(self) -> bool:
        raise NotImplementedError


class _SocketConn(_Conn):
    """Unix domain socket transport, drained by a background reader thread."""

    def __init__(self, sock: socket.socket):
        self._sock: socket.socket | None = sock
        self._pending: dict[str, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._reader: threading.Thread | None = None

    def _read_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            sock = self._sock
            if sock is None:
                raise ConnectionError("Discord IPC disconnected")
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Discord IPC disconnected")
            buf += chunk
        return buf

    def send(self, opcode: int, payload: dict) -> None:
        sock = self._sock
        if sock is None:
            raise ConnectionError("Discord IPC disconnected")
        sock.sendall(_pack(opcode, payload))

    def read_frame(self, timeout: float = 15.0) -> tuple[int, dict]:
        return _read_frame(self._read_exact)

    def start(self) -> None:
        self._reader = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader.start()

    def _reader_loop(self) -> None:
        """Reads messages, answers PINGs, delivers responses by nonce."""
        try:
            while True:
                op, msg = _read_frame(self._read_exact)
                if op == OP_PING:
                    self.send(OP_PONG, msg)
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
            self.close()
            # Wake up any waiting callers so they can see the connection is gone
            with self._pending_lock:
                for q in self._pending.values():
                    q.put(None)

    def request(self, cmd: str, args: dict, timeout: float = 15.0) -> dict | None:
        nonce = str(uuid.uuid4())
        q: queue.Queue = queue.Queue()
        with self._pending_lock:
            self._pending[nonce] = q
        try:
            self.send(OP_FRAME, {"cmd": cmd, "args": args, "nonce": nonce})
            try:
                return q.get(timeout=timeout)
            except queue.Empty:
                raise DiscordRPCError(
                    "Discord IPC timed out — is Discord running and not frozen?"
                )
        finally:
            with self._pending_lock:
                self._pending.pop(nonce, None)

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

    @property
    def alive(self) -> bool:
        return self._sock is not None


class _PipeConn(_Conn):
    """Windows named pipe transport, driven request/response by the caller."""

    # How often to ask the pipe whether anything has arrived while waiting.
    _POLL_S = 0.02

    def __init__(self, path: str):
        self._f = open(path, "r+b", buffering=0)
        self._handle = wintypes.HANDLE(msvcrt.get_osfhandle(self._f.fileno()))
        # One round trip at a time: the request and the response it is reading
        # are a single indivisible use of the handle.
        self._lock = threading.Lock()

    def _wait_readable(self, deadline: float) -> None:
        avail = wintypes.DWORD(0)
        while True:
            if self._f.closed:
                raise ConnectionError("Discord IPC disconnected")
            if not _kernel32.PeekNamedPipe(
                self._handle, None, 0, None, ctypes.byref(avail), None
            ):
                raise ConnectionError("Discord IPC disconnected")
            if avail.value:
                return
            if time.monotonic() >= deadline:
                raise DiscordRPCError(
                    "Discord IPC timed out — is Discord running and not frozen?"
                )
            time.sleep(self._POLL_S)

    def _read_exact(self, n: int, deadline: float) -> bytes:
        buf = b""
        while len(buf) < n:
            self._wait_readable(deadline)
            chunk = self._f.read(n - len(buf))
            if not chunk:
                raise ConnectionError("Discord IPC disconnected")
            buf += chunk
        return buf

    def send(self, opcode: int, payload: dict) -> None:
        if self._f.closed:
            raise ConnectionError("Discord IPC disconnected")
        self._f.write(_pack(opcode, payload))

    def read_frame(self, timeout: float = 15.0) -> tuple[int, dict]:
        deadline = time.monotonic() + timeout
        return _read_frame(lambda n: self._read_exact(n, deadline))

    def request(self, cmd: str, args: dict, timeout: float = 15.0) -> dict | None:
        nonce = str(uuid.uuid4())
        deadline = time.monotonic() + timeout
        if not self._lock.acquire(timeout=timeout):
            raise DiscordRPCError(
                "Discord IPC timed out — is Discord running and not frozen?"
            )
        try:
            self.send(OP_FRAME, {"cmd": cmd, "args": args, "nonce": nonce})
            while True:
                op, msg = _read_frame(lambda n: self._read_exact(n, deadline))
                if op == OP_PING:
                    self.send(OP_PONG, msg)
                    continue
                if op == OP_CLOSE:
                    self.close()
                    return None
                # Subscribed events carry no nonce, and the answer to a request
                # that already timed out carries a stale one. Only our own reply
                # ends the wait.
                if msg.get("nonce") == nonce:
                    return msg
        finally:
            self._lock.release()

    def close(self) -> None:
        try:
            self._f.close()
        except Exception:
            pass

    @property
    def alive(self) -> bool:
        return not self._f.closed


def _connect_ipc() -> _Conn:
    """Open a connection to the first Discord IPC endpoint that answers."""
    if _IS_WINDOWS:
        for path in _windows_pipe_paths():
            try:
                return _PipeConn(path)
            except OSError:
                continue
    else:
        for path in _unix_socket_paths():
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(path)
            except OSError:
                sock.close()
                continue
            return _SocketConn(sock)
    raise DiscordRPCError("Discord IPC socket not found — is Discord running?")


def _handshake(client_id: str) -> _Conn:
    """Connect and complete the v1 handshake, returning a ready connection."""
    conn = _connect_ipc()
    try:
        conn.send(OP_HANDSHAKE, {"v": 1, "client_id": client_id})
        op, msg = conn.read_frame(_CONNECT_TIMEOUT)
        if op == OP_CLOSE or msg.get("evt") != "READY":
            raise DiscordRPCError(f"Handshake failed: {msg}")
        conn.start()
    except Exception:
        conn.close()
        raise
    return conn


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
        self._conn: _Conn | None = None
        self._conn_lock = threading.Lock()

        self._load_tokens()

    # ── Token persistence ──────────────────────────────────────────────────

    def _load_tokens(self):
        if self._load_tokens_from_credentials():
            return
        self._migrate_legacy_token_file()

    def _load_tokens_from_credentials(self) -> bool:
        try:
            store = _core_store()
            if store is not None:
                data = store.load(_PLUGIN_KEY)
            else:
                if not _CREDS_PATH.is_file():
                    return False
                with _CREDS_PATH.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                data = raw.get(_PLUGIN_KEY)
                if not isinstance(data, dict) or not (
                    data.get("access_token") or data.get("refresh_token")
                ):
                    data = raw.get(_LEGACY_PLUGIN_KEY)
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
        store = _core_store()
        if store is not None:
            try:
                store.update(_PLUGIN_KEY, {
                    "client_id": self.client_id,
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                    "token_expiry": self._token_expiry,
                })
            except Exception:
                pass
            return
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
        store = _core_store()
        if store is not None:
            try:
                store.update(_PLUGIN_KEY, {"access_token": "", "refresh_token": "", "token_expiry": ""})
            except Exception:
                pass
        try:
            if store is None and _CREDS_PATH.is_file():
                with _CREDS_PATH.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    for key in (_PLUGIN_KEY, _LEGACY_PLUGIN_KEY):
                        creds = raw.get(key, {})
                        if isinstance(creds, dict):
                            for k in ("access_token", "refresh_token",
                                      "token_expiry", "expiry"):
                                creds.pop(k, None)
                            raw[key] = creds
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

    def _disconnect(self):
        with self._conn_lock:
            conn = self._conn
            self._conn = None
        if conn is not None:
            conn.close()

    def _connect_and_auth(self):
        """Open the IPC connection, handshake, and authenticate."""
        if time.time() >= self._token_expiry - 60:
            if not self._refresh_access_token():
                raise DiscordRPCError("Token expired — please re-authorize")

        conn = _handshake(self.client_id)
        try:
            resp = conn.request(
                "AUTHENTICATE",
                {"access_token": self._access_token},
                timeout=_CONNECT_TIMEOUT,
            )
        except Exception:
            conn.close()
            raise
        if resp is None or resp.get("evt") == "ERROR":
            conn.close()
            # Discard ALL tokens so the next press triggers a full re-authorization
            # rather than looping: refreshing produces a new token that also fails.
            self.clear_tokens()
            err_data = (resp or {}).get("data", {})
            err_msg = err_data.get("message") or err_data.get("code") or str(resp)
            raise DiscordRPCError(f"Authentication failed: {err_msg}")

        with self._conn_lock:
            self._conn = conn

    def _ensure_connected(self) -> _Conn:
        """Return the active authenticated connection, reconnecting if needed."""
        with self._conn_lock:
            conn = self._conn
        if conn is not None and conn.alive:
            return conn
        self._connect_and_auth()
        with self._conn_lock:
            conn = self._conn
        if conn is None:
            # Another thread evicted the connection between the two steps.
            raise DiscordRPCError("Lost connection to Discord")
        return conn

    # ── Public API ─────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        """True when an authenticated IPC connection is already open.

        Callers use this to tell "we can talk to Discord right now" from "we
        would have to open a connection first", which costs a handshake.
        """
        conn = self._conn
        return conn is not None and conn.alive

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
        conn = _handshake(self.client_id)
        try:
            # AUTHORIZE blocks until the user interacts with Discord's consent
            # dialog, so it gets a far longer timeout than an ordinary command.
            resp = conn.request("AUTHORIZE", {
                "client_id": self.client_id,
                "scopes": _SCOPES,
            }, timeout=120)

            if resp is None:
                raise DiscordRPCError("Connection closed while waiting for authorization")
            if resp.get("evt") == "ERROR":
                raise DiscordRPCError(resp["data"].get("message", str(resp)))

            code = resp["data"]["code"]
            self._exchange_code(code)
        finally:
            conn.close()

        # Pre-establish the persistent connection now that we have a token
        try:
            self._connect_and_auth()
        except Exception:
            pass  # Will reconnect on first use

    def get_voice_settings(self) -> dict:
        """Return the current voice settings as {"mute": bool, "deaf": bool}."""
        conn = self._ensure_connected()
        try:
            resp = conn.request("GET_VOICE_SETTINGS", {})
            if resp is None:
                raise DiscordRPCError("Lost connection to Discord")
        except (DiscordRPCError, OSError):
            self._disconnect()
            raise
        data = resp.get("data", {})
        return {"mute": bool(data.get("mute", False)), "deaf": bool(data.get("deaf", False))}

    def toggle_mute(self) -> dict:
        """Toggle mute and return the confirmed voice settings {"mute": bool, "deaf": bool}."""
        conn = self._ensure_connected()
        try:
            resp = conn.request("GET_VOICE_SETTINGS", {})
            if resp is None:
                raise DiscordRPCError("Lost connection to Discord")
            muted = resp["data"].get("mute", False)
            deafened = resp["data"].get("deaf", False)
            # When deafened, Discord treats the mute button as "undeafen" — mimic
            # that behaviour so the button clears both states and updates both icons.
            if deafened:
                set_resp = conn.request("SET_VOICE_SETTINGS", {"deaf": False})
            else:
                set_resp = conn.request("SET_VOICE_SETTINGS", {"mute": not muted})
        except (DiscordRPCError, OSError):
            self._disconnect()
            raise
        # SET_VOICE_SETTINGS returns the full updated settings in data
        confirmed = (set_resp or {}).get("data", resp["data"])
        return {"mute": bool(confirmed.get("mute", not muted)), "deaf": bool(confirmed.get("deaf", False))}

    def toggle_deafen(self) -> dict:
        """Toggle deafen and return the confirmed voice settings {"mute": bool, "deaf": bool}."""
        conn = self._ensure_connected()
        try:
            resp = conn.request("GET_VOICE_SETTINGS", {})
            if resp is None:
                raise DiscordRPCError("Lost connection to Discord")
            deafened = resp["data"].get("deaf", False)
            set_resp = conn.request("SET_VOICE_SETTINGS", {"deaf": not deafened})
        except (DiscordRPCError, OSError):
            self._disconnect()
            raise
        confirmed = (set_resp or {}).get("data", resp["data"])
        return {"mute": bool(confirmed.get("mute", False)), "deaf": bool(confirmed.get("deaf", not deafened))}
