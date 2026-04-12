"""Folder navigation plugin for profile-scoped folder layouts."""

from __future__ import annotations

from typing import Any, Dict, List

from lib import config as config_lib
from lib import folders as folders_lib
from lib import profiles as profiles_lib


ROOT_FOLDER = config_lib.DEFAULT_FOLDER


def _read_stack() -> list[str]:
    stack = config_lib.get_folder_stack()
    return [str(item) for item in stack if str(item).strip()]


def _write_stack(stack: list[str]) -> None:
    config_lib.set_folder_stack(stack)


def api_profiles(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """Return all profiles as label/value pairs for the api_select UI."""
    try:
        return [{"label": p, "value": p} for p in profiles_lib.get_profiles()]
    except Exception:
        return []


def switch_profile(config: Dict[str, Any]) -> Dict[str, Any]:
    """Switch to the configured profile."""
    profile_name = str(config.get("profile_name") or "").strip()
    if not profile_name:
        return {"success": False, "error": "No profile selected"}

    current = config_lib.get_active_profile()
    if profile_name == current:
        return {"success": True, "profile_change": False}

    try:
        profiles_lib.change_profile(profile_name)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    return {"success": True, "profile_change": True}


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

    # Persist per-folder auto-return settings from the Enter Folder button
    # config so runtime behavior does not depend on a separate UI sync call.
    auto_enabled = bool(config.get("auto_return_enabled"))
    auto_seconds_raw = config.get("auto_return_seconds", 5)
    auto_show_text = config.get("auto_return_show_text", True)
    try:
        auto_seconds = int(auto_seconds_raw)
    except (TypeError, ValueError):
        auto_seconds = 5
    if auto_seconds < 0:
        auto_seconds = 5
    try:
        folders_lib.upsert_folder(
            folder_id,
            display_name=folder_id,
            extra_fields={
                "auto_return_enabled": auto_enabled,
                "auto_return_seconds": auto_seconds,
                "auto_return_show_text": bool(auto_show_text),
            },
        )
    except Exception:
        pass

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
