"""Utilities plugin for PyDeck.

Opens URLs in the default browser, sends HTTP requests, and runs scripts.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------


_KNOWN_BROWSERS: List[tuple] = [
    ("firefox",                "Firefox"),
    ("zen-browser",            "Zen Browser"),
    ("google-chrome-stable",   "Google Chrome"),
    ("google-chrome",          "Google Chrome"),
    ("chromium",               "Chromium"),
    ("chromium-browser",       "Chromium"),
    ("brave-browser",          "Brave"),
    ("brave",                  "Brave"),
    ("microsoft-edge-stable",  "Microsoft Edge"),
    ("microsoft-edge",         "Microsoft Edge"),
    ("opera",                  "Opera"),
    ("vivaldi-stable",         "Vivaldi"),
    ("vivaldi",                "Vivaldi"),
    ("epiphany",               "GNOME Web"),
    ("falkon",                 "Falkon"),
    ("midori",                 "Midori"),
    ("waterfox",               "Waterfox"),
    ("librewolf",              "LibreWolf"),
    ("floorp",                 "Floorp"),
    ("thorium-browser",        "Thorium"),
]


_DESKTOP_TO_LABEL: Dict[str, str] = {
    "firefox":                 "Firefox",
    "zen-browser":             "Zen Browser",
    "zen_browser":             "Zen Browser",
    "google-chrome":           "Google Chrome",
    "chromium":                "Chromium",
    "chromium-browser":        "Chromium",
    "brave-browser":           "Brave",
    "microsoft-edge":          "Microsoft Edge",
    "opera":                   "Opera",
    "vivaldi":                 "Vivaldi",
    "vivaldi-stable":          "Vivaldi",
    "epiphany":                "GNOME Web",
    "falkon":                  "Falkon",
    "midori":                  "Midori",
    "waterfox":                "Waterfox",
    "librewolf":               "LibreWolf",
    "floorp":                  "Floorp",
    "thorium-browser":         "Thorium",
}


def _detect_default_browser_name() -> Optional[str]:
    """Return a friendly name for the system default browser, or None."""
    try:
        out = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    # out is like "firefox.desktop" or "google-chrome.desktop"
    stem = out.removesuffix(".desktop").lower()
    # try exact match first, then prefix match
    if stem in _DESKTOP_TO_LABEL:
        return _DESKTOP_TO_LABEL[stem]
    for key, label in _DESKTOP_TO_LABEL.items():
        if stem.startswith(key) or key.startswith(stem):
            return label
    return stem.replace("-", " ").title() or None


def api_browsers(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return installed browsers for the api_select dropdown."""

    default_name = _detect_default_browser_name()
    default_label = f"System Default ({default_name})" if default_name else "System Default"
    results = [{"label": default_label, "value": "default"}]
    seen_labels: set = set()

    for binary, label in _KNOWN_BROWSERS:
        if label in seen_labels:
            continue
        if shutil.which(binary):
            results.append({"label": label, "value": binary})
            seen_labels.add(label)

    return results


def _build_display_env() -> dict:
    """Build an environment with display vars for launching GUI apps.

    When PyDeck runs as a systemd service the process has no DISPLAY,
    WAYLAND_DISPLAY, or XAUTHORITY. We reconstruct them from well-known
    runtime paths so xdg-open can reach the user's desktop session on both
    Wayland and X11.
    """
    env = dict(os.environ)
    uid = os.getuid()

    if "XDG_RUNTIME_DIR" not in env:
        env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"

    runtime_dir = env["XDG_RUNTIME_DIR"]

    # Wayland: find the compositor socket in the runtime dir.
    if "WAYLAND_DISPLAY" not in env:
        for candidate in ("wayland-1", "wayland-0"):
            if os.path.exists(os.path.join(runtime_dir, candidate)):
                env["WAYLAND_DISPLAY"] = candidate
                break

    # X11: discover the display number from existing sockets instead of
    # guessing :0, then supply the auth file so connections are accepted.
    if "DISPLAY" not in env:
        x11_socket_dir = "/tmp/.X11-unix"
        try:
            sockets = sorted(os.listdir(x11_socket_dir))
            for s in sockets:
                if s.startswith("X"):
                    env["DISPLAY"] = f":{s[1:]}"
                    break
        except OSError:
            pass
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"

    if "XAUTHORITY" not in env:
        xauth = Path.home() / ".Xauthority"
        if xauth.exists():
            env["XAUTHORITY"] = str(xauth)

    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"

    # Hyprland: hyprctl needs HYPRLAND_INSTANCE_SIGNATURE to find the IPC
    # socket at $XDG_RUNTIME_DIR/hypr/<sig>/.socket.sock.
    if "HYPRLAND_INSTANCE_SIGNATURE" not in env:
        hypr_dir = os.path.join(runtime_dir, "hypr")
        try:
            entries = sorted(os.listdir(hypr_dir))
            for entry in entries:
                sock = os.path.join(hypr_dir, entry, ".socket.sock")
                if os.path.exists(sock):
                    env["HYPRLAND_INSTANCE_SIGNATURE"] = entry
                    break
        except OSError:
            pass

    # Sway / wlroots: swaymsg reads SWAYSOCK for the compositor socket.
    if "SWAYSOCK" not in env:
        try:
            for name in sorted(os.listdir(runtime_dir)):
                if name.startswith("sway-ipc.") and name.endswith(".sock"):
                    env["SWAYSOCK"] = os.path.join(runtime_dir, name)
                    break
        except OSError:
            pass

    return env


def open_url(config: Dict[str, Any]) -> Dict[str, Any]:
    """Open the configured URL in the default browser or a specific one."""

    url = str(config.get("url") or "https://youtube.com")
    browser = str(config.get("browser") or "default").strip()
    env = _build_display_env()

    # Build the command: specific browser binary or xdg-open for the default.
    cmd = [browser, url] if browser != "default" else ["xdg-open", url]

    try:
        subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"success": True, "url": url, "browser": browser, "message": "Browser launch attempted"}
    except FileNotFoundError:
        if browser != "default":
            return {
                "success": False,
                "url": url,
                "browser": browser,
                "error": f"Browser not found: {browser}",
            }

    # xdg-open not available; fall back to webbrowser module
    opened = webbrowser.open(url, new=2)
    return {
        "success": bool(opened),
        "url": url,
        "browser": browser,
        "message": "Browser launch attempted",
    }


# ---------------------------------------------------------------------------
# Web Requests
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Scripts
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_THROBBER_IMAGE = "plugins/plugin/utilities/img/throbber.gif"

_running_jobs: Dict[int, Dict[str, Any]] = {}
_running_jobs_lock = threading.Lock()


def _normalize_runtime(value: Any) -> str:
    runtime = str(value or "bash").strip().lower()
    return runtime if runtime in {"bash", "python"} else "bash"


def _normalize_script_path(value: Any) -> str:
    return str(value or "").strip()


def _normalize_args(value: Any) -> List[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    return shlex.split(raw)


def _normalize_timeout(value: Any) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        return 30
    if timeout < 1:
        return 1
    if timeout > 600:
        return 600
    return timeout


def _button_id(value: Any) -> Optional[int]:
    try:
        button_id = int(value)
    except (TypeError, ValueError):
        return None
    return button_id if button_id >= 0 else None


def _resolve_working_dir(value: Any) -> Optional[Path]:
    raw = str(value or "").strip()
    if not raw:
        return None
    wd = Path(raw).expanduser().resolve()
    if not wd.exists() or not wd.is_dir():
        raise ValueError(f"Working directory does not exist: {wd}")
    return wd


def _resolve_script_path(
    script_path: str,
    working_dir: Optional[Path],
) -> Path:
    p = Path(script_path).expanduser()
    if p.is_absolute():
        resolved = p.resolve()
    elif working_dir is not None:
        resolved = (working_dir / p).resolve()
    else:
        resolved = (_PROJECT_ROOT / p).resolve()

    if not resolved.exists() or not resolved.is_file():
        raise ValueError(f"Script file not found: {resolved}")
    return resolved


def _build_command(
    runtime: str,
    script_path: Path,
    args: List[str],
    python_executable: str,
) -> List[str]:
    if runtime == "python":
        py = python_executable.strip() or "python3"
        return [py, "-S", str(script_path), *args]
    return ["bash", str(script_path), *args]


def _cleanup_job(button_id: int) -> None:
    with _running_jobs_lock:
        _running_jobs.pop(button_id, None)


def _get_job(button_id: int) -> Optional[Dict[str, Any]]:
    with _running_jobs_lock:
        return _running_jobs.get(button_id)


def _set_job(button_id: int, job: Dict[str, Any]) -> None:
    with _running_jobs_lock:
        _running_jobs[button_id] = job


def _spawn_image_helper(
    button_id: int,
    script_pid: int,
    buttons_path: Path,
    original_image: Any,
) -> None:
    helper_code = r'''
import json
import os
import sys
import time
from pathlib import Path

button_id = int(sys.argv[1])
script_pid = int(sys.argv[2])
buttons_path = Path(sys.argv[3])
original_arg = sys.argv[4] if len(sys.argv) > 4 else '__NONE__'
original_image = original_arg if original_arg != '__NONE__' else None
throbber_image = sys.argv[5]


def update_image(image):
    try:
        payload = json.loads(buttons_path.read_text(encoding='utf-8'))
        if not isinstance(payload, dict):
            return
        buttons = payload.get('buttons')
        if not isinstance(buttons, list):
            return
        for button in buttons:
            if not isinstance(button, dict) or button.get('id') != button_id:
                continue
            display = button.get('display')
            if not isinstance(display, dict):
                display = {}
            display['image'] = image
            button['display'] = display
            buttons_path.write_text(
                json.dumps(payload, indent=2) + '\n',
                encoding='utf-8',
            )
            return
    except Exception:
        return


def process_alive(pid):
    stat_path = Path(f'/proc/{pid}/stat')
    try:
        stat = stat_path.read_text(encoding='utf-8')
    except OSError:
        return False
    parts = stat.split()
    if len(parts) < 3:
        return False
    return parts[2] != 'Z'


time.sleep(0.5)
if not process_alive(script_pid):
    sys.exit(0)
update_image(throbber_image)

while process_alive(script_pid):
    time.sleep(0.05)

update_image(original_image)'''
    try:
        subprocess.Popen(
            [
                "python3",
                "-u",
                "-c",
                helper_code,
                str(button_id),
                str(script_pid),
                str(buttons_path),
                "__NONE__" if original_image is None else str(original_image),
                _THROBBER_IMAGE,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        pass


def _start_script(
    button_id: Optional[int],
    command: List[str],
    working_dir: Optional[Path],
    timeout: int,
    original_image: Any,
) -> Dict[str, Any]:
    if button_id is None:
        return {
            "success": False,
            "error": "Button id unavailable.",
        }

    with _running_jobs_lock:
        prior = _running_jobs.get(button_id)
    if prior:
        prior_proc = prior.get("proc")
        if (
            isinstance(prior_proc, subprocess.Popen)
            and prior_proc.poll() is None
        ):
            try:
                prior_proc.terminate()
            except OSError:
                pass

    try:
        # Start from the display-aware environment so GUI apps and compositor
        # tools (hyprctl, swaymsg, alacritty…) can find their sockets and
        # displays, then layer safety flags on top.
        minimal_env = _build_display_env()
        minimal_env.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PIP_NO_INPUT": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_BUILD_ISOLATION": "1",
            "PIP_NO_DEPS": "1",
            "PYTHONUNBUFFERED": "1",
        })
        proc = subprocess.Popen(
            command,
            cwd=str(working_dir) if working_dir else None,
            env=minimal_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return {
            "success": False,
            "error": f"Failed to start script: {exc}",
        }
    try:
        from lib import button as button_lib
        buttons_path = button_lib.get_active_buttons_path()
        _spawn_image_helper(
            button_id,
            proc.pid,
            buttons_path,
            original_image,
        )
    except OSError:
        pass
    _set_job(
        button_id,
        {
            "proc": proc,
            "started_at": time.time(),
            "timeout": timeout,
            "original_image": original_image,
            "throbber_shown": False,
        },
    )

    return {
        "success": True,
        "message": "Script started.",
    }


def poll_run_script(config: Dict[str, Any]) -> Dict[str, Any]:
    """Update the button icon while a background script is running."""

    button_id = _button_id(config.get("_button_id"))
    if button_id is None:
        return {}

    job = _get_job(button_id)
    if not job:
        return {}

    proc = job.get("proc")
    if not isinstance(proc, subprocess.Popen):
        _cleanup_job(button_id)
        return {}

    now = time.time()
    started_at = float(job.get("started_at") or now)
    timeout = int(job.get("timeout") or 0)
    original_image = job.get("original_image")
    elapsed = now - started_at

    if proc.poll() is None and timeout > 0 and elapsed >= timeout:
        try:
            proc.kill()
        except OSError:
            pass
        proc.poll()

    if proc.poll() is None:
        if elapsed >= 0.5 and not bool(job.get("throbber_shown")):
            job["throbber_shown"] = True
            _set_job(button_id, job)
            return {"display_update": {"image": _THROBBER_IMAGE}}
        return {}

    if bool(job.get("throbber_shown")):
        _cleanup_job(button_id)
        return {
            "display_update": {
                "image": original_image if original_image else None,
            }
        }

    _cleanup_job(button_id)
    return {}


def run_script(config: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a configured script and return process result data."""

    cfg = dict(config or {})
    runtime = _normalize_runtime(cfg.get("runtime"))
    script_raw = _normalize_script_path(cfg.get("script_path"))
    if not script_raw:
        return {
            "success": False,
            "runtime": runtime,
            "error": "Script Path is required.",
        }

    try:
        args = _normalize_args(cfg.get("args"))
    except ValueError as exc:
        return {
            "success": False,
            "runtime": runtime,
            "error": f"Invalid arguments: {exc}",
        }

    timeout = _normalize_timeout(cfg.get("timeout_seconds"))
    python_executable = str(cfg.get("python_executable") or "python3")

    try:
        working_dir = _resolve_working_dir(cfg.get("working_dir"))
        script_path = _resolve_script_path(script_raw, working_dir)
        command = _build_command(runtime, script_path, args, python_executable)
    except ValueError as exc:
        return {
            "success": False,
            "runtime": runtime,
            "error": str(exc),
        }

    return {
        **_start_script(
            _button_id(cfg.get("_button_id")),
            command,
            working_dir,
            timeout,
            cfg.get("_button_image"),
        ),
        "runtime": runtime,
        "command": command,
        "script": str(script_path),
        "cwd": str(working_dir) if working_dir else "",
    }
