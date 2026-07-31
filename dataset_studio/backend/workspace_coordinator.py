from __future__ import annotations

import fcntl
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Callable


class WorkspaceRecoveryRequiredError(RuntimeError):
    pass


class WorkspaceSnapshotIntegrityError(RuntimeError):
    pass


def workspace_studio_root(root: Path) -> Path:
    dataset_root = Path(root)
    studio = dataset_root / ".dataset_studio"
    if studio.is_symlink():
        raise WorkspaceSnapshotIntegrityError(f".dataset_studio must not be a symlink: {studio}")
    try:
        studio.resolve(strict=False).relative_to(dataset_root.resolve(strict=False))
    except (OSError, ValueError) as error:
        raise WorkspaceSnapshotIntegrityError(
            f".dataset_studio escapes the dataset root: {studio}"
        ) from error
    return studio


def transition_marker_path(root: Path) -> Path:
    return workspace_studio_root(root) / "workspace_transition.json"


def _recovery_required(root: Path) -> WorkspaceRecoveryRequiredError:
    marker_path = transition_marker_path(root)
    try:
        import json

        marker = json.loads(marker_path.read_text())
    except Exception:
        marker = {}
    studio = marker_path.parent
    restore = marker.get("restore_path") or str(studio / ".restore-*")
    rollback = marker.get("rollback_path") or str(studio / ".rollback-*")
    message = (
        f"Interrupted workspace transition marker detected at {marker_path}. "
        "Stop the app and do not use the curation workspace until manual recovery is complete. "
        f"Preserve and inspect restore path {restore}, rollback path {rollback}, "
        f"and {studio / 'saved_workspaces' / '.recovery-*'}; compare them with "
        "workspace_registry.json and the active claims.json, dataset_checkpoints.json, and workspaces/ targets. "
        "After selecting one complete, internally consistent workspace state, remove only the marker and obsolete "
        "transition recovery paths, then restart the app."
    )
    return WorkspaceRecoveryRequiredError(message)


@contextmanager
def workspace_state_lock(root: Path, *, exclusive: bool = False):
    """Coordinate full workspace-state operations across threads and processes."""
    studio = workspace_studio_root(root)
    studio.mkdir(parents=True, exist_ok=True)
    with (studio / "workspace_state.lock").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            if transition_marker_path(root).exists():
                raise _recovery_required(root)
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def shared_workspace_operation(function: Callable):
    @wraps(function)
    def protected(root: Path, *args, **kwargs):
        with workspace_state_lock(root):
            return function(root, *args, **kwargs)

    return protected
