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
    temporary = path.parent / f".tmp-{uuid.uuid4().hex}"
    try:
        with temporary.open("w") as handle:
            json.dump(registry, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


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


def _remove_target(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _replace_with_retry(source: Path, destination: Path) -> None:
    last_error: OSError | None = None
    for _ in range(2):
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            last_error = error
    assert last_error is not None
    raise last_error


def _copy_recovery_target(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True)
    else:
        shutil.copy2(source, destination)


class _Activation:
    def __init__(self, restore: Path, rollback: Path):
        self.restore = restore
        self.rollback = rollback
        self.moved_to_rollback: list[str] = []
        self.installed: list[str] = []

    def rollback_active_state(self, studio: Path) -> tuple[list[Exception], bool]:
        """Restore active targets and report whether recovery copies must be retained."""
        errors: list[Exception] = []
        retain_recovery = False
        for target in reversed(self.installed):
            installed_path = studio / target
            if not installed_path.exists():
                continue
            try:
                _remove_target(installed_path)
            except Exception as error:
                errors.append(error)
                retain_recovery = True
        for target in reversed(self.moved_to_rollback):
            rollback_path = self.rollback / target
            if not rollback_path.exists():
                continue
            try:
                _replace_with_retry(rollback_path, studio / target)
            except OSError as move_error:
                retain_recovery = True
                try:
                    _copy_recovery_target(rollback_path, studio / target)
                except Exception as copy_error:
                    errors.extend((move_error, copy_error))
        return errors, retain_recovery

    def cleanup(self) -> None:
        if self.restore.exists():
            shutil.rmtree(self.restore)
        if self.rollback.exists():
            shutil.rmtree(self.rollback)


def _restore_after_failed_activation(activation: _Activation, studio: Path, original_error: Exception) -> None:
    errors, retain_recovery = activation.rollback_active_state(studio)
    if not errors and not retain_recovery:
        activation.cleanup()
    if errors:
        raise original_error from errors[0]
    raise original_error


def _persist_registry_after_activation(root: Path, registry: dict, activation: _Activation) -> None:
    try:
        _write_registry(root, registry)
    except Exception as registry_error:
        _restore_after_failed_activation(activation, _studio_root(root), registry_error)
    else:
        activation.cleanup()


def _activate_restore(root: Path, restore: Path) -> _Activation:
    studio = _studio_root(root)
    rollback = studio / f".rollback-{uuid.uuid4().hex}"
    rollback.mkdir()
    activation = _Activation(restore, rollback)
    try:
        for target in ACTIVE_TARGETS:
            current = studio / target
            if current.exists():
                os.replace(current, rollback / target)
                activation.moved_to_rollback.append(target)
        for target in ACTIVE_TARGETS:
            staged = restore / target
            if staged.exists():
                os.replace(staged, studio / target)
                activation.installed.append(target)
        return activation
    except Exception as activation_error:
        _restore_after_failed_activation(activation, studio, activation_error)


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
        activation = _activate_restore(root, _empty_restore(root))

        previous.update(snapshot_workspace)
        active = _new_workspace(new_name)
        registry["workspaces"].append(active)
        registry["active_workspace_id"] = active["id"]
        _persist_registry_after_activation(root, registry, activation)
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
        activation = _activate_restore(root, _copy_snapshot_to_restore(root, selected["id"]))

        previous["updated_at"] = _now()
        selected["updated_at"] = _now()
        registry["active_workspace_id"] = selected["id"]
        _persist_registry_after_activation(root, registry, activation)
        return {"previous_workspace": copy.deepcopy(previous), "active_workspace": copy.deepcopy(selected)}
