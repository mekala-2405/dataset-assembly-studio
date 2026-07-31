from __future__ import annotations

import json
import re
from pathlib import Path

from .workspaces import _locked_json


DEFAULT_SETTINGS = {
    "output_name": "assembled_lerobot_v21",
    "output_parent": "",
    "second_camera": "front",
    "max_per_task": None,
    "required_cameras": ["wrist", "front"],
    "fps": 30,
    "width": 640,
    "height": 480,
    "codec": "h264",
}


def _settings_file(root: Path) -> Path:
    return root / ".dataset_studio" / "settings.json"


def _normalized(root: Path, payload: dict | None = None) -> dict:
    values = {**DEFAULT_SETTINGS, **(payload or {})}
    name = str(values["output_name"]).strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("output_name must be a single folder name")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("output_name may contain letters, numbers, dot, dash, and underscore")
    second = str(values["second_camera"]).strip()
    if not second or second == "wrist":
        raise ValueError("second_camera must be a non-wrist camera name")
    cap = values.get("max_per_task")
    if cap in ("", None):
        cap = None
    else:
        cap = int(cap)
        if cap < 1:
            raise ValueError("max_per_task must be at least 1")
    parent = str(values.get("output_parent") or root / "exports")
    return {
        "output_name": name,
        "output_parent": parent,
        "second_camera": second,
        "max_per_task": cap,
        "required_cameras": ["wrist", second],
        "fps": 30,
        "width": 640,
        "height": 480,
        "codec": "h264",
    }


def load_settings(root: Path) -> dict:
    path = _settings_file(root)
    if not path.exists():
        return _normalized(root)
    try:
        return _normalized(root, json.loads(path.read_text()))
    except (json.JSONDecodeError, TypeError):
        return _normalized(root)


def save_settings(root: Path, payload: dict) -> dict:
    settings = _normalized(root, payload)
    with _locked_json(_settings_file(root), {}) as stored:
        stored.clear()
        stored.update(settings)
    return settings
