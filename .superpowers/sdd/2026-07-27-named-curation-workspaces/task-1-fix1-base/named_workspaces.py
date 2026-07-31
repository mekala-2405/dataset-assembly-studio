from __future__ import annotations

import copy
import fcntl
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


ACTIVE_TARGETS = ("claims.json", "dataset_checkpoints.json", "workspaces")
NEW_CONFIRMATION = "START NEW WORKSPACE"
SWITCH_CONFIRMATION = "SWITCH WORKSPACE"


def _studio_root(root: Path) -> Path:
    return Path(root) / ".dataset_studio"


def _registry_file(root: Path) -> Path:
    return _studio_root(root) / "workspace_registry.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _registry_lock(root: Path):
    studio = _studio_root(root)
    studio.mkdir(parents=True, exist_ok=True)
    with (studio / "workspace_registry.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read_registry(root: Path) -> dict | None:
    path = _registry_file(root)
    return json.loads(path.read_text()) if path.exists() else None


def _write_registry(root: Path, registry: dict) -> None:
    path = _registry_file(root)
    path.write_text(json.dumps(registry, indent=2, sort_keys=True))


def _new_workspace(name: str) -> dict:
    timestamp = _now()
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def _ensure_registry(root: Path) -> dict:
    registry = _read_registry(root)
    if registry is not None:
        return registry
    workspace = _new_workspace("Current workspace")
    registry = {"active_workspace_id": workspace["id"], "workspaces": [workspace]}
    _write_registry(root, registry)
    return registry


def ensure_workspace_registry(root: Path) -> dict:
    """Return the named-workspace registry without changing the active state."""
    with _registry_lock(root):
        return copy.deepcopy(_ensure_registry(root))


def _validate_name(name: str, label: str = "workspace name") -> str:
    normalized = str(name).strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    if "/" in normalized or "\\" in normalized:
        raise ValueError(f"{label} must not contain a slash")
    return normalized


def _active_workspace(registry: dict) -> dict:
    active_id = registry["active_workspace_id"]
    for workspace in registry["workspaces"]:
        if workspace["id"] == active_id:
            return workspace
    raise ValueError("active workspace is missing from the registry")


def _validate_new_name(registry: dict, name: str, ignored_id: str | None = None) -> str:
    normalized = _validate_name(name)
    existing = {
        workspace["name"].casefold()
        for workspace in registry["workspaces"]
        if workspace["id"] != ignored_id
    }
    if normalized.casefold() in existing:
        raise ValueError("workspace name already exists")
    return normalized


def _validate_json_files(directory: Path) -> None:
    for path in directory.rglob("*.json"):
        json.loads(path.read_text())


def _snapshot_workspace(root: Path, workspace: dict) -> Path:
    """Copy active targets into a validated snapshot, replacing any earlier one safely."""
    studio = _studio_root(root)
    saved = studio / "saved_workspaces"
    saved.mkdir(parents=True, exist_ok=True)
    temporary = saved / f".tmp-{uuid.uuid4().hex}"
    final = saved / workspace["id"]
    recovery: Path | None = None
    try:
        temporary.mkdir()
        (temporary / "workspace.json").write_text(json.dumps(workspace, indent=2, sort_keys=True))
        for target in ACTIVE_TARGETS:
            source = studio / target
            destination = temporary / target
            if not source.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        _validate_json_files(temporary)
        if final.exists():
            recovery = saved / f".recovery-{workspace['id']}-{_now().replace(':', '-')}-{uuid.uuid4().hex}"
            os.replace(final, recovery)
        try:
            os.replace(temporary, final)
        except Exception:
            if recovery is not None and recovery.exists():
                os.replace(recovery, final)
            raise
        if recovery is not None and recovery.exists():
            shutil.rmtree(recovery)
        return final
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def _copy_snapshot_to_restore(root: Path, workspace_id: str) -> Path:
    studio = _studio_root(root)
    snapshot = studio / "saved_workspaces" / workspace_id
    if not snapshot.is_dir():
        raise ValueError("workspace snapshot is missing")
    restore = studio / f".restore-{uuid.uuid4().hex}"
    try:
        restore.mkdir()
        for target in ACTIVE_TARGETS:
            source = snapshot / target
            destination = restore / target
            if not source.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        _validate_json_files(restore)
        return restore
    except Exception:
        if restore.exists():
            shutil.rmtree(restore)
        raise


def _empty_restore(root: Path) -> Path:
    studio = _studio_root(root)
    restore = studio / f".restore-{uuid.uuid4().hex}"
    restore.mkdir()
    (restore / "claims.json").write_text(json.dumps({"claims": {}}))
    (restore / "dataset_checkpoints.json").write_text(json.dumps({"checkpoints": {}, "history": {}}))
    (restore / "workspaces").mkdir()
    _validate_json_files(restore)
    return restore


def _activate_restore(root: Path, restore: Path) -> None:
    studio = _studio_root(root)
    rollback = studio / f".rollback-{uuid.uuid4().hex}"
    rollback.mkdir()
    moved_to_rollback: list[str] = []
    installed: list[str] = []
    try:
        for target in ACTIVE_TARGETS:
            current = studio / target
            if current.exists():
                os.replace(current, rollback / target)
                moved_to_rollback.append(target)
        for target in ACTIVE_TARGETS:
            staged = restore / target
            if staged.exists():
                os.replace(staged, studio / target)
                installed.append(target)
    except Exception:
        for target in reversed(installed):
            installed_path = studio / target
            if installed_path.exists():
                if installed_path.is_dir():
                    shutil.rmtree(installed_path)
                else:
                    installed_path.unlink()
        for target in reversed(moved_to_rollback):
            rollback_path = rollback / target
            if rollback_path.exists():
                os.replace(rollback_path, studio / target)
        raise
    finally:
        if restore.exists():
            shutil.rmtree(restore)
        if rollback.exists():
            shutil.rmtree(rollback)


def create_named_workspace(root: Path, current_name: str, new_name: str, confirmation: str) -> dict:
    if confirmation != NEW_CONFIRMATION:
        raise ValueError(f"confirmation must be {NEW_CONFIRMATION}")
    with _registry_lock(root):
        registry = _ensure_registry(root)
        previous = _active_workspace(registry)
        current_name = _validate_new_name(registry, current_name, ignored_id=previous["id"])
        new_name = _validate_new_name(registry, new_name, ignored_id=previous["id"])
        if current_name.casefold() == new_name.casefold():
            raise ValueError("workspace name already exists")

        snapshot_workspace = {**previous, "name": current_name, "updated_at": _now()}
        _snapshot_workspace(root, snapshot_workspace)
        restore = _empty_restore(root)
        _activate_restore(root, restore)

        previous.update(snapshot_workspace)
        active = _new_workspace(new_name)
        registry["workspaces"].append(active)
        registry["active_workspace_id"] = active["id"]
        _write_registry(root, registry)
        return {"previous_workspace": copy.deepcopy(previous), "active_workspace": copy.deepcopy(active)}


def switch_named_workspace(root: Path, workspace_id: str, confirmation: str) -> dict:
    if confirmation != SWITCH_CONFIRMATION:
        raise ValueError(f"confirmation must be {SWITCH_CONFIRMATION}")
    with _registry_lock(root):
        registry = _ensure_registry(root)
        previous = _active_workspace(registry)
        selected = next((item for item in registry["workspaces"] if item["id"] == workspace_id), None)
        if selected is None:
            raise ValueError("workspace does not exist")

        _snapshot_workspace(root, previous)
        restore = _copy_snapshot_to_restore(root, selected["id"])
        _activate_restore(root, restore)

        previous["updated_at"] = _now()
        selected["updated_at"] = _now()
        registry["active_workspace_id"] = selected["id"]
        _write_registry(root, registry)
        return {"previous_workspace": copy.deepcopy(previous), "active_workspace": copy.deepcopy(selected)}
