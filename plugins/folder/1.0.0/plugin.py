"""Folder navigation plugin for profile-scoped folder layouts."""

from __future__ import annotations

from typing import Any, Dict

from lib import config as config_lib
from lib import folders as folders_lib


ROOT_FOLDER = config_lib.DEFAULT_FOLDER


def _read_stack() -> list[str]:
    stack = config_lib.get_folder_stack()
    return [str(item) for item in stack if str(item).strip()]


def _write_stack(stack: list[str]) -> None:
    config_lib.set_folder_stack(stack)


def enter_folder(config: Dict[str, Any]) -> Dict[str, Any]:
    """Switch active folder to the configured folder id."""

    folder_id = str(config.get("folder_id") or "").strip()
    if not folder_id:
        return {
            "success": False,
            "error": "Missing folder_id",
        }

    current_folder = config_lib.get_active_folder()
    if folder_id == current_folder:
        return {
            "success": True,
            "folder_change": False,
            "active_folder": current_folder,
        }

    try:
        active_folder = folders_lib.change_folder(folder_id)
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "folder_change": False,
        }

    stack = _read_stack()
    stack.append(current_folder)
    _write_stack(stack)

    return {
        "success": True,
        "folder_change": True,
        "active_folder": active_folder,
    }


def return_folder(config: Dict[str, Any]) -> Dict[str, Any]:
    """Return to parent folder or root based on return_mode."""

    mode = str(config.get("return_mode") or "parent").strip().lower()
    if mode not in {"parent", "root"}:
        mode = "parent"

    current_folder = config_lib.get_active_folder()
    stack = _read_stack()

    if mode == "root":
        _write_stack([])
        if current_folder == ROOT_FOLDER:
            return {
                "success": True,
                "folder_change": False,
                "active_folder": ROOT_FOLDER,
            }

        active_folder = config_lib.set_active_folder(ROOT_FOLDER)
        return {
            "success": True,
            "folder_change": True,
            "active_folder": active_folder,
        }

    target_folder = ROOT_FOLDER
    if stack:
        target_folder = stack.pop()
        _write_stack(stack)

    if target_folder == ROOT_FOLDER:
        if current_folder == ROOT_FOLDER:
            return {
                "success": False,
                "error": "Already at root folder",
                "folder_change": False,
                "active_folder": ROOT_FOLDER,
            }

        active_folder = config_lib.set_active_folder(ROOT_FOLDER)
        return {
            "success": True,
            "folder_change": True,
            "active_folder": active_folder,
        }

    try:
        active_folder = folders_lib.change_folder(target_folder)
    except ValueError:
        # If parent folder was deleted, fall back safely to root.
        _write_stack([])
        active_folder = config_lib.set_active_folder(ROOT_FOLDER)

    return {
        "success": True,
        "folder_change": active_folder != current_folder,
        "active_folder": active_folder,
    }
