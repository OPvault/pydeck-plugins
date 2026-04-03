"""Script Runner plugin for PyDeck.

Runs Bash or Python script files with optional arguments.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib import button as button_lib

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_THROBBER_IMAGE = "plugins/plugin/script-runner/img/throbber.gif"

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
        # Resolve relative paths from repo root by default.
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


def _trim_output(value: str) -> str:
    return value


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
        minimal_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "USER": os.environ.get("USER", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PIP_NO_INPUT": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_BUILD_ISOLATION": "1",
            "PIP_NO_DEPS": "1",
            "PYTHONUNBUFFERED": "1",
        }
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


def _running_icon_preload() -> List[Dict[str, Any]]:
    return [
        {
            "offset_ms": 500,
            "display_update": {
                "image": _THROBBER_IMAGE,
            },
        }
    ]


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
