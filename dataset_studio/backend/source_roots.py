from __future__ import annotations

import json
from pathlib import Path

from .workspaces import _locked_json


def _sources_root_file(state_root: Path) -> Path:
    return state_root / ".dataset_studio" / "sources_root.json"


def load_sources_root(state_root: Path) -> Path:
    """Resolve the folder to scan for datasets, falling back to the state root."""
    path = _sources_root_file(state_root)
    if path.exists():
        try:
            stored = json.loads(path.read_text()).get("path")
            if stored:
                return Path(stored)
        except (json.JSONDecodeError, OSError, TypeError, AttributeError):
            pass
    return Path(state_root)


def save_sources_root(state_root: Path, sources_root: Path) -> Path:
    with _locked_json(_sources_root_file(state_root), {}) as stored:
        stored.clear()
        stored.update({"path": str(sources_root)})
    return sources_root
