from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import fcntl

from .workspace_coordinator import shared_workspace_operation


@contextmanager
def _locked_json(path: Path, default: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        try:
            data = json.load(handle)
        except json.JSONDecodeError:
            data = default
        yield data
        handle.seek(0)
        handle.truncate()
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)


def _user_file(root: Path, user: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", user).strip("_")
    if not safe:
        raise ValueError("user name must contain letters or numbers")
    return root / ".dataset_studio" / "workspaces" / f"{safe}.json"


@shared_workspace_operation
def load_workspace(root: Path, user: str) -> dict:
    path = _user_file(root, user)
    if not path.exists():
        return {"user": user, "checkpoints": {}}
    return json.loads(path.read_text())


@shared_workspace_operation
def save_checkpoint(root: Path, user: str, dataset_path: str, status: str, recipe: dict) -> dict:
    if status not in {"draft", "approved", "excluded"}:
        raise ValueError("status must be draft, approved, or excluded")
    if status == "excluded" and not str(recipe.get("reason", "")).strip():
        raise ValueError("excluded checkpoints require a reason")
    with _locked_json(_shared_file(root), {"checkpoints": {}, "history": {}}) as shared:
        shared.setdefault("checkpoints", {})
        shared.setdefault("history", {})
        prior_shared = shared["checkpoints"].get(dataset_path, {})
        shared_checkpoint = {
            "status": status,
            "recipe": json.loads(json.dumps(recipe)),
            "revision": prior_shared.get("revision", 0) + 1,
            "updated_by": user,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        shared["checkpoints"][dataset_path] = shared_checkpoint
        shared["history"].setdefault(dataset_path, []).append(json.loads(json.dumps(shared_checkpoint)))
    path = _user_file(root, user)
    with _locked_json(path, {"user": user, "checkpoints": {}}) as workspace:
        prior = workspace["checkpoints"].get(dataset_path, {})
        workspace["checkpoints"][dataset_path] = {"status": status, "recipe": recipe, "revision": prior.get("revision", 0) + 1}
        result = json.loads(json.dumps(workspace))
        result["shared_checkpoint"] = shared_checkpoint
        return result


def _shared_file(root: Path) -> Path:
    return root / ".dataset_studio" / "dataset_checkpoints.json"


@shared_workspace_operation
def load_shared_checkpoints(root: Path) -> dict:
    path = _shared_file(root)
    if not path.exists():
        return {"checkpoints": {}, "history": {}}
    result = json.loads(path.read_text())
    result.setdefault("checkpoints", {})
    result.setdefault("history", {})
    return result


@shared_workspace_operation
def checkpoint_history(root: Path, dataset_path: str) -> list[dict]:
    return load_shared_checkpoints(root).get("history", {}).get(dataset_path, [])


@shared_workspace_operation
def migrate_legacy_workspaces(root: Path) -> int:
    """Promote pre-shared workspace checkpoints without overwriting newer shared state."""
    workspace_root = root / ".dataset_studio" / "workspaces"
    if not workspace_root.is_dir():
        return 0
    legacy: list[tuple[str, str, dict]] = []
    for path in sorted(workspace_root.glob("*.json")):
        try:
            workspace = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        user = str(workspace.get("user") or path.stem)
        for dataset_path, checkpoint in (workspace.get("checkpoints") or {}).items():
            legacy.append((user, dataset_path, checkpoint))
    migrated = 0
    with _locked_json(_shared_file(root), {"checkpoints": {}, "history": {}}) as shared:
        shared.setdefault("checkpoints", {})
        shared.setdefault("history", {})
        for user, dataset_path, checkpoint in legacy:
            if dataset_path in shared["checkpoints"]:
                continue
            record = {
                "status": checkpoint.get("status", "draft"),
                "recipe": json.loads(json.dumps(checkpoint.get("recipe") or {})),
                "revision": max(1, int(checkpoint.get("revision", 1))),
                "updated_by": user,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            shared["checkpoints"][dataset_path] = record
            shared["history"].setdefault(dataset_path, []).append(json.loads(json.dumps(record)))
            migrated += 1
        for dataset_path, checkpoint in shared["checkpoints"].items():
            if shared["history"].get(dataset_path):
                continue
            record = json.loads(json.dumps(checkpoint))
            record.setdefault("updated_by", "legacy")
            record.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
            shared["history"][dataset_path] = [record]
    return migrated


def _claims_file(root: Path) -> Path:
    return root / ".dataset_studio" / "claims.json"


@shared_workspace_operation
def claim_dataset(root: Path, user: str, dataset_path: str) -> dict:
    with _locked_json(_claims_file(root), {"claims": {}}) as claims:
        owner = claims["claims"].get(dataset_path)
        if owner and owner != user:
            raise ValueError(f"dataset is claimed by {owner}")
        claims["claims"][dataset_path] = user
        return json.loads(json.dumps(claims))


@shared_workspace_operation
def release_dataset(root: Path, user: str, dataset_path: str) -> dict:
    with _locked_json(_claims_file(root), {"claims": {}}) as claims:
        owner = claims["claims"].get(dataset_path)
        if owner and owner != user:
            raise ValueError(f"dataset is claimed by {owner}")
        claims["claims"].pop(dataset_path, None)
        return json.loads(json.dumps(claims))


@shared_workspace_operation
def release_all_claims(root: Path, user: str) -> dict:
    with _locked_json(_claims_file(root), {"claims": {}}) as claims:
        claims["claims"] = {path: owner for path, owner in claims["claims"].items() if owner != user}
        return json.loads(json.dumps(claims))


@shared_workspace_operation
def load_claims(root: Path) -> dict:
    path = _claims_file(root)
    return json.loads(path.read_text()) if path.exists() else {"claims": {}}
