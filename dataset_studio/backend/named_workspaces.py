from __future__ import annotations

import copy
import fcntl
import json
import logging
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .workspace_coordinator import (
    WorkspaceRecoveryRequiredError,
    WorkspaceSnapshotIntegrityError,
    transition_marker_path,
    workspace_studio_root,
    workspace_state_lock,
)


ACTIVE_TARGETS = ("claims.json", "dataset_checkpoints.json", "workspaces")
NEW_CONFIRMATION = "START NEW WORKSPACE"
SWITCH_CONFIRMATION = "SWITCH WORKSPACE"
LOGGER = logging.getLogger(__name__)
WORKSPACE_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


class WorkspaceRequestValidationError(ValueError):
    pass


class WorkspaceNotFoundError(ValueError):
    pass


class WorkspaceRegistryCommitUncertainError(WorkspaceSnapshotIntegrityError):
    pass


def _studio_root(root: Path) -> Path:
    return workspace_studio_root(root)


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
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise WorkspaceSnapshotIntegrityError(f"workspace registry must be a regular file: {path}")
    try:
        registry = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise WorkspaceSnapshotIntegrityError(f"workspace registry is unreadable JSON: {path}: {error}") from error
    return _validate_registry(registry)


def _validate_registry(registry: object) -> dict:
    if not isinstance(registry, dict):
        raise WorkspaceSnapshotIntegrityError("workspace registry must contain a JSON object")
    active_id = registry.get("active_workspace_id")
    workspaces = registry.get("workspaces")
    if not isinstance(active_id, str) or not WORKSPACE_ID_PATTERN.fullmatch(active_id):
        raise WorkspaceSnapshotIntegrityError("workspace registry active_workspace_id is invalid")
    if not isinstance(workspaces, list) or not workspaces:
        raise WorkspaceSnapshotIntegrityError("workspace registry workspaces must be a non-empty list")

    ids: set[str] = set()
    names: set[str] = set()
    for index, workspace in enumerate(workspaces):
        if not isinstance(workspace, dict):
            raise WorkspaceSnapshotIntegrityError(f"workspace registry entry {index} must be an object")
        for field in ("id", "name", "created_at", "updated_at"):
            if not isinstance(workspace.get(field), str) or not workspace[field]:
                raise WorkspaceSnapshotIntegrityError(
                    f"workspace registry entry {index} field {field!r} is invalid"
                )
        workspace_id = workspace["id"]
        if not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
            raise WorkspaceSnapshotIntegrityError(
                f"workspace registry entry {index} has an invalid workspace ID"
            )
        if workspace_id in ids:
            raise WorkspaceSnapshotIntegrityError("workspace registry contains duplicate workspace IDs")
        ids.add(workspace_id)
        normalized_name = workspace["name"].strip()
        if not normalized_name or "/" in normalized_name or "\\" in normalized_name:
            raise WorkspaceSnapshotIntegrityError(
                f"workspace registry entry {index} has an invalid workspace name"
            )
        folded_name = normalized_name.casefold()
        if folded_name in names:
            raise WorkspaceSnapshotIntegrityError("workspace registry contains duplicate workspace names")
        names.add(folded_name)
    if active_id not in ids:
        raise WorkspaceSnapshotIntegrityError("active workspace is missing from the registry")
    return registry


def _write_registry(root: Path, registry: dict) -> None:
    _validate_registry(registry)
    path = _registry_file(root)
    temporary = path.parent / f".tmp-{uuid.uuid4().hex}"
    replaced = False
    try:
        with temporary.open("w") as handle:
            json.dump(registry, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        replaced = True
        _fsync_directory(path.parent)
    except Exception as error:
        if temporary.exists():
            temporary.unlink()
        if replaced:
            raise WorkspaceRegistryCommitUncertainError(
                f"workspace registry replacement at {path} could not be durably synced; "
                "the transition marker and recovery paths were retained"
            ) from error
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


def _saved_workspaces_directory(root: Path, *, create: bool) -> Path:
    studio = _studio_root(root)
    saved = studio / "saved_workspaces"
    if saved.is_symlink() or (saved.exists() and not saved.is_dir()):
        raise WorkspaceSnapshotIntegrityError(f"saved workspace root must be a directory: {saved}")
    if create:
        saved.mkdir(parents=True, exist_ok=True)
    try:
        saved.resolve(strict=False).relative_to(studio.resolve(strict=False))
    except ValueError as error:
        raise WorkspaceSnapshotIntegrityError(
            f"saved workspace root escapes .dataset_studio: {saved}"
        ) from error
    return saved


def _workspace_snapshot_path(root: Path, workspace_id: str, *, create_saved: bool) -> Path:
    if not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
        raise WorkspaceSnapshotIntegrityError(f"workspace registry contains an invalid workspace ID: {workspace_id!r}")
    saved = _saved_workspaces_directory(root, create=create_saved)
    snapshot = saved / workspace_id
    try:
        snapshot.resolve(strict=False).relative_to(saved.resolve(strict=False))
    except ValueError as error:
        raise WorkspaceSnapshotIntegrityError(
            f"workspace snapshot path escapes saved_workspaces: {snapshot}"
        ) from error
    return snapshot


def ensure_workspace_registry(root: Path) -> dict:
    """Return the named-workspace registry without changing the active state."""
    with workspace_state_lock(root, exclusive=True), _registry_lock(root):
        return copy.deepcopy(_ensure_registry(root))


def _validate_name(name: str, label: str = "workspace name") -> str:
    normalized = str(name).strip()
    if not normalized:
        raise WorkspaceRequestValidationError(f"{label} must not be blank")
    if "/" in normalized or "\\" in normalized:
        raise WorkspaceRequestValidationError(f"{label} must not contain a slash")
    return normalized


def _active_workspace(registry: dict) -> dict:
    active_id = registry["active_workspace_id"]
    for workspace in registry["workspaces"]:
        if workspace["id"] == active_id:
            return workspace
    raise WorkspaceSnapshotIntegrityError("active workspace is missing from the registry")


def _validate_new_name(registry: dict, name: str, ignored_id: str | None = None) -> str:
    normalized = _validate_name(name)
    existing = {
        workspace["name"].casefold()
        for workspace in registry["workspaces"]
        if workspace["id"] != ignored_id
    }
    if normalized.casefold() in existing:
        raise WorkspaceRequestValidationError("workspace name already exists")
    return normalized


def _read_json_object(path: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise WorkspaceSnapshotIntegrityError(f"{label} is unreadable JSON: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise WorkspaceSnapshotIntegrityError(f"{label} must contain a JSON object: {path}")
    return payload


def _validate_workspace_metadata(directory: Path, expected_workspace: dict) -> None:
    path = directory / "workspace.json"
    if path.is_symlink() or not path.is_file():
        raise WorkspaceSnapshotIntegrityError(f"workspace snapshot metadata must be a regular file: {path}")
    metadata = _read_json_object(path, "workspace snapshot metadata")
    if metadata.get("id") != expected_workspace["id"]:
        raise WorkspaceSnapshotIntegrityError(
            f"workspace snapshot ID {metadata.get('id')!r} does not match registry ID {expected_workspace['id']!r}: {path}"
        )
    for key in ("id", "name", "created_at", "updated_at"):
        if not isinstance(metadata.get(key), str) or not metadata[key]:
            raise WorkspaceSnapshotIntegrityError(f"workspace snapshot metadata field {key!r} is invalid: {path}")


def _validate_state_targets(directory: Path, *, allow_missing: bool) -> None:
    claims_path = directory / "claims.json"
    checkpoints_path = directory / "dataset_checkpoints.json"
    workspaces_path = directory / "workspaces"
    for path, expected in (
        (claims_path, "file"),
        (checkpoints_path, "file"),
        (workspaces_path, "directory"),
    ):
        if path.is_symlink():
            raise WorkspaceSnapshotIntegrityError(f"workspace snapshot target must not be a symlink: {path}")
        if not path.exists():
            if allow_missing:
                continue
            raise WorkspaceSnapshotIntegrityError(f"workspace snapshot target is missing: {path}")
        if expected == "file" and not path.is_file():
            raise WorkspaceSnapshotIntegrityError(f"workspace snapshot target must be a regular file: {path}")
        if expected == "directory" and not path.is_dir():
            raise WorkspaceSnapshotIntegrityError(f"workspace snapshot target must be a directory: {path}")

    if claims_path.exists():
        claims = _read_json_object(claims_path, "claims snapshot")
        if not isinstance(claims.get("claims"), dict):
            raise WorkspaceSnapshotIntegrityError(f"claims snapshot requires a top-level claims object: {claims_path}")
    if checkpoints_path.exists():
        checkpoints = _read_json_object(checkpoints_path, "checkpoint snapshot")
        if not isinstance(checkpoints.get("checkpoints"), dict) or not isinstance(checkpoints.get("history"), dict):
            raise WorkspaceSnapshotIntegrityError(
                f"checkpoint snapshot requires top-level checkpoints and history objects: {checkpoints_path}"
            )
    if workspaces_path.exists():
        for path in workspaces_path.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise WorkspaceSnapshotIntegrityError(
                    f"user workspace snapshot entries must be regular JSON files: {path}"
                )
            workspace = _read_json_object(path, "user workspace snapshot")
            if not isinstance(workspace.get("checkpoints"), dict):
                raise WorkspaceSnapshotIntegrityError(
                    f"user workspace snapshot requires a top-level checkpoints object: {path}"
                )
            if "user" in workspace and not isinstance(workspace["user"], str):
                raise WorkspaceSnapshotIntegrityError(f"user workspace snapshot user must be a string: {path}")


def _validate_snapshot(directory: Path, expected_workspace: dict) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise WorkspaceSnapshotIntegrityError(f"workspace snapshot is missing or not a directory: {directory}")
    _validate_workspace_metadata(directory, expected_workspace)
    _validate_state_targets(directory, allow_missing=True)


def _write_canonical_target(path: Path, target: str) -> None:
    if target == "claims.json":
        path.write_text(json.dumps({"claims": {}}))
    elif target == "dataset_checkpoints.json":
        path.write_text(json.dumps({"checkpoints": {}, "history": {}}))
    else:
        path.mkdir()


def _snapshot_workspace(root: Path, workspace: dict) -> Path:
    """Copy active targets into a validated snapshot, replacing any earlier one safely."""
    studio = _studio_root(root)
    _validate_state_targets(studio, allow_missing=True)
    saved = _saved_workspaces_directory(root, create=True)
    temporary = saved / f".tmp-{uuid.uuid4().hex}"
    final = _workspace_snapshot_path(root, workspace["id"], create_saved=True)
    recovery: Path | None = None
    try:
        temporary.mkdir()
        (temporary / "workspace.json").write_text(json.dumps(workspace, indent=2, sort_keys=True))
        for target in ACTIVE_TARGETS:
            source = studio / target
            destination = temporary / target
            if not source.exists():
                _write_canonical_target(destination, target)
                continue
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        _validate_snapshot(temporary, workspace)
        _fsync_tree(temporary)
        if final.exists():
            if final.is_symlink() or not final.is_dir():
                raise WorkspaceSnapshotIntegrityError(f"existing workspace snapshot is not a directory: {final}")
            recovery = saved / f".recovery-{workspace['id']}-{_now().replace(':', '-')}-{uuid.uuid4().hex}"
            os.replace(final, recovery)
            _fsync_directory(saved)
        try:
            os.replace(temporary, final)
            _fsync_directory(saved)
        except Exception:
            if recovery is not None and recovery.exists():
                os.replace(recovery, final)
                _fsync_directory(saved)
            raise
        if recovery is not None and recovery.exists():
            try:
                shutil.rmtree(recovery)
                _fsync_directory(saved)
            except Exception as error:
                LOGGER.warning("cleanup retained saved-workspace recovery path %s: %s", recovery, error)
        return final
    except Exception:
        if temporary.exists():
            try:
                shutil.rmtree(temporary)
            except Exception as cleanup_error:
                LOGGER.warning("cleanup retained temporary snapshot path %s: %s", temporary, cleanup_error)
        raise


def _copy_snapshot_to_restore(root: Path, workspace: dict) -> Path:
    studio = _studio_root(root)
    snapshot = _workspace_snapshot_path(root, workspace["id"], create_saved=False)
    _validate_snapshot(snapshot, workspace)
    restore = studio / f".restore-{uuid.uuid4().hex}"
    try:
        restore.mkdir()
        for target in ACTIVE_TARGETS:
            source = snapshot / target
            destination = restore / target
            if not source.exists():
                _write_canonical_target(destination, target)
                continue
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        _validate_state_targets(restore, allow_missing=False)
        _fsync_tree(restore)
        _fsync_directory(studio)
        return restore
    except Exception:
        if restore.exists():
            try:
                shutil.rmtree(restore)
            except Exception as cleanup_error:
                LOGGER.warning("cleanup retained temporary restore path %s: %s", restore, cleanup_error)
        raise


def _empty_restore(root: Path) -> Path:
    studio = _studio_root(root)
    restore = studio / f".restore-{uuid.uuid4().hex}"
    restore.mkdir()
    for target in ACTIVE_TARGETS:
        _write_canonical_target(restore / target, target)
    _validate_state_targets(restore, allow_missing=False)
    _fsync_tree(restore)
    _fsync_directory(studio)
    return restore


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_tree(path: Path) -> None:
    if path.is_symlink():
        raise WorkspaceSnapshotIntegrityError(f"workspace state must not contain symlinks: {path}")
    if path.is_file():
        _fsync_file(path)
        return
    if not path.is_dir():
        raise WorkspaceSnapshotIntegrityError(f"workspace state path is not a file or directory: {path}")
    for child in path.iterdir():
        _fsync_tree(child)
    _fsync_directory(path)


def _read_transition_marker(root: Path) -> dict:
    return json.loads(transition_marker_path(root).read_text())


def _write_transition_marker(root: Path, marker: dict) -> None:
    path = transition_marker_path(root)
    temporary = path.parent / f".tmp-transition-{uuid.uuid4().hex}"
    try:
        with temporary.open("w") as handle:
            json.dump(marker, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _remove_transition_marker(root: Path) -> None:
    path = transition_marker_path(root)
    if path.exists():
        path.unlink()
        _fsync_directory(path.parent)


def _start_transition_marker(
    root: Path,
    *,
    operation: str,
    previous_workspace_id: str,
    target_workspace_id: str,
    restore: Path,
) -> None:
    _write_transition_marker(root, {
        "version": 1,
        "operation": operation,
        "phase": "activating",
        "previous_workspace_id": previous_workspace_id,
        "target_workspace_id": target_workspace_id,
        "restore_path": str(restore),
        "rollback_path": None,
        "updated_at": _now(),
    })


def _update_transition_marker(root: Path, **changes) -> None:
    marker = _read_transition_marker(root)
    marker.update(changes)
    marker["updated_at"] = _now()
    _write_transition_marker(root, marker)


def _cleanup_marker_after_commit(root: Path, activation: _Activation, warnings: list[str]) -> bool:
    marker_path = transition_marker_path(root)
    try:
        marker = _read_transition_marker(root)
    except Exception:
        marker = {
            "version": 1,
            "operation": "unknown",
            "phase": "committed",
            "restore_path": str(activation.restore),
            "rollback_path": str(activation.rollback),
            "updated_at": _now(),
        }
    try:
        _remove_transition_marker(root)
        return True
    except Exception as error:
        marker.update({
            "phase": "committed",
            "restore_path": str(activation.restore),
            "rollback_path": str(activation.rollback),
            "updated_at": _now(),
        })
        try:
            _write_transition_marker(root, marker)
        except Exception as rewrite_error:
            rewrite_warning = f"could not durably rewrite committed transition marker {marker_path}: {rewrite_error}"
            LOGGER.warning(rewrite_warning)
            warnings.append(rewrite_warning)
        warning = (
            f"cleanup retained transition marker {marker_path} and recovery paths "
            f"{activation.restore}, {activation.rollback}: {error}"
        )
        LOGGER.warning(warning)
        warnings.append(warning)
        return False


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
        try:
            for target in self.moved_to_rollback:
                active_path = studio / target
                if active_path.exists():
                    _fsync_tree(active_path)
            _fsync_directory(self.rollback)
            _fsync_directory(studio)
        except Exception as sync_error:
            errors.append(sync_error)
            retain_recovery = True
        return errors, retain_recovery

    def cleanup(self) -> list[str]:
        warnings: list[str] = []
        for path in (self.restore, self.rollback):
            if not path.exists():
                continue
            try:
                shutil.rmtree(path)
                _fsync_directory(path.parent)
            except Exception as error:
                warning = f"cleanup retained recovery path {path}: {error}"
                LOGGER.warning(warning)
                warnings.append(warning)
        return warnings


def _restore_after_failed_activation(
    root: Path,
    activation: _Activation,
    studio: Path,
    original_error: Exception,
) -> None:
    errors, retain_recovery = activation.rollback_active_state(studio)
    if not errors and not retain_recovery:
        try:
            _remove_transition_marker(root)
        except Exception as marker_error:
            errors.append(marker_error)
        else:
            activation.cleanup()
    if errors:
        raise original_error from errors[0]
    raise original_error


def _persist_registry_after_activation(root: Path, registry: dict, activation: _Activation) -> list[str]:
    try:
        _write_registry(root, registry)
    except WorkspaceRegistryCommitUncertainError:
        raise
    except Exception as registry_error:
        _restore_after_failed_activation(root, activation, _studio_root(root), registry_error)
    warnings: list[str] = []
    try:
        _update_transition_marker(root, phase="committed")
    except Exception as error:
        warning = f"could not update committed transition marker {transition_marker_path(root)}: {error}"
        LOGGER.warning(warning)
        warnings.append(warning)
    if _cleanup_marker_after_commit(root, activation, warnings):
        warnings.extend(activation.cleanup())
    return warnings


def _activate_restore(root: Path, restore: Path) -> _Activation:
    studio = _studio_root(root)
    rollback = studio / f".rollback-{uuid.uuid4().hex}"
    rollback.mkdir()
    _fsync_directory(studio)
    activation = _Activation(restore, rollback)
    try:
        _update_transition_marker(root, rollback_path=str(rollback))
        for target in ACTIVE_TARGETS:
            current = studio / target
            if current.exists():
                os.replace(current, rollback / target)
                activation.moved_to_rollback.append(target)
        _fsync_directory(rollback)
        _fsync_directory(studio)
        for target in ACTIVE_TARGETS:
            staged = restore / target
            if staged.exists():
                os.replace(staged, studio / target)
                activation.installed.append(target)
        _fsync_directory(restore)
        _fsync_directory(studio)
        return activation
    except Exception as activation_error:
        _restore_after_failed_activation(root, activation, studio, activation_error)


def create_named_workspace(
    root: Path,
    current_name: str,
    new_name: str,
    confirmation: str,
    transition_guard: Callable[[], None] | None = None,
) -> dict:
    if confirmation != NEW_CONFIRMATION:
        raise WorkspaceRequestValidationError(f"confirmation must be {NEW_CONFIRMATION}")
    with workspace_state_lock(root, exclusive=True), _registry_lock(root):
        if transition_guard is not None:
            transition_guard()
        registry = _ensure_registry(root)
        previous = _active_workspace(registry)
        current_name = _validate_new_name(registry, current_name, ignored_id=previous["id"])
        new_name = _validate_new_name(registry, new_name, ignored_id=previous["id"])
        if current_name.casefold() == new_name.casefold():
            raise WorkspaceRequestValidationError("workspace name already exists")

        snapshot_workspace = {**previous, "name": current_name, "updated_at": _now()}
        _snapshot_workspace(root, snapshot_workspace)
        restore = _empty_restore(root)
        active = _new_workspace(new_name)
        _start_transition_marker(
            root,
            operation="create",
            previous_workspace_id=previous["id"],
            target_workspace_id=active["id"],
            restore=restore,
        )
        activation = _activate_restore(root, restore)
        try:
            _update_transition_marker(root, phase="registry_pending")
        except Exception as marker_error:
            _restore_after_failed_activation(root, activation, _studio_root(root), marker_error)

        previous.update(snapshot_workspace)
        registry["workspaces"].append(active)
        registry["active_workspace_id"] = active["id"]
        cleanup_warnings = _persist_registry_after_activation(root, registry, activation)
        return {
            "previous_workspace": copy.deepcopy(previous),
            "active_workspace": copy.deepcopy(active),
            "cleanup_warnings": cleanup_warnings,
        }


def switch_named_workspace(
    root: Path,
    workspace_id: str,
    confirmation: str,
    transition_guard: Callable[[], None] | None = None,
) -> dict:
    if confirmation != SWITCH_CONFIRMATION:
        raise WorkspaceRequestValidationError(f"confirmation must be {SWITCH_CONFIRMATION}")
    with workspace_state_lock(root, exclusive=True), _registry_lock(root):
        if transition_guard is not None:
            transition_guard()
        registry = _ensure_registry(root)
        previous = _active_workspace(registry)
        selected = next((item for item in registry["workspaces"] if item["id"] == workspace_id), None)
        if selected is None:
            raise WorkspaceNotFoundError("workspace does not exist")

        _snapshot_workspace(root, previous)
        restore = _copy_snapshot_to_restore(root, selected)
        _start_transition_marker(
            root,
            operation="switch",
            previous_workspace_id=previous["id"],
            target_workspace_id=selected["id"],
            restore=restore,
        )
        activation = _activate_restore(root, restore)
        try:
            _update_transition_marker(root, phase="registry_pending")
        except Exception as marker_error:
            _restore_after_failed_activation(root, activation, _studio_root(root), marker_error)

        previous["updated_at"] = _now()
        selected["updated_at"] = _now()
        registry["active_workspace_id"] = selected["id"]
        cleanup_warnings = _persist_registry_after_activation(root, registry, activation)
        return {
            "previous_workspace": copy.deepcopy(previous),
            "active_workspace": copy.deepcopy(selected),
            "cleanup_warnings": cleanup_warnings,
        }
