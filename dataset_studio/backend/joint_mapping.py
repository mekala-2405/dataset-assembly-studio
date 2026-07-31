from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pyarrow as pa


CANONICAL_JOINTS = (
    "shoulder_pan.pos",
    "shoulder_lift.pos",
    "elbow_flex.pos",
    "wrist_flex.pos",
    "wrist_roll.pos",
    "gripper.pos",
)


@dataclass(frozen=True)
class JointContract:
    action_names: tuple[str, ...]
    state_names: tuple[str, ...]
    action_shape: tuple[int, ...]
    state_shape: tuple[int, ...]
    proposal: dict[str, dict[str, int]]
    compatible: bool
    errors: tuple[str, ...]

    def to_dict(self) -> dict:
        result = asdict(self)
        result["canonical_joints"] = list(CANONICAL_JOINTS)
        return result


def normalize_joint_name(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
    if value.startswith("main_"):
        value = value[5:]
    if value.endswith("_pos"):
        value = value[:-4]
    return value


def _proposal(names: tuple[str, ...]) -> dict[str, int]:
    normalized: dict[str, list[int]] = {}
    for index, name in enumerate(names):
        normalized.setdefault(normalize_joint_name(name), []).append(index)
    result: dict[str, int] = {}
    for canonical in CANONICAL_JOINTS:
        matches = normalized.get(normalize_joint_name(canonical), [])
        if len(matches) == 1:
            result[canonical] = matches[0]
    return result


def contract_from_names(
    action_names: list[str] | tuple[str, ...],
    state_names: list[str] | tuple[str, ...],
    action_shape: list[int] | tuple[int, ...] | None = None,
    state_shape: list[int] | tuple[int, ...] | None = None,
) -> JointContract:
    action_names = tuple(str(name) for name in action_names)
    state_names = tuple(str(name) for name in state_names)
    action_shape = tuple(action_shape or (len(action_names),))
    state_shape = tuple(state_shape or (len(state_names),))
    errors = []
    if action_shape != (6,):
        errors.append(f"action has {action_shape[0] if action_shape else 0} positions; exactly 6 are required")
    if state_shape != (6,):
        errors.append(f"observation.state has {state_shape[0] if state_shape else 0} positions; exactly 6 are required")
    proposal = {
        "action": _proposal(action_names),
        "observation.state": _proposal(state_names),
    }
    if len(proposal["action"]) != 6:
        errors.append("action joint names could not be mapped automatically")
    if len(proposal["observation.state"]) != 6:
        errors.append("observation.state joint names could not be mapped automatically")
    return JointContract(
        action_names=action_names,
        state_names=state_names,
        action_shape=action_shape,
        state_shape=state_shape,
        proposal=proposal,
        compatible=not errors,
        errors=tuple(errors),
    )


def build_joint_contract(dataset_path: Path) -> JointContract:
    info = json.loads((Path(dataset_path) / "meta" / "info.json").read_text())
    features = info.get("features") or {}
    action = features.get("action") or {}
    state = features.get("observation.state") or {}
    return contract_from_names(
        action.get("names") or [],
        state.get("names") or [],
        action.get("shape") or [],
        state.get("shape") or [],
    )


def validate_joint_mapping(mapping: dict, contract: JointContract) -> list[str]:
    errors = [error for error in contract.errors if "could not be mapped automatically" not in error]
    for feature in ("action", "observation.state"):
        feature_mapping = mapping.get(feature)
        if not isinstance(feature_mapping, dict):
            errors.append(f"{feature} mapping is missing")
            continue
        missing = [name for name in CANONICAL_JOINTS if name not in feature_mapping]
        extra = [name for name in feature_mapping if name not in CANONICAL_JOINTS]
        if missing:
            errors.append(f"{feature} mapping is missing: {', '.join(missing)}")
        if extra:
            errors.append(f"{feature} mapping has unknown slots: {', '.join(extra)}")
        positions = [feature_mapping.get(name) for name in CANONICAL_JOINTS if name in feature_mapping]
        if any(isinstance(position, bool) or not isinstance(position, int) for position in positions):
            errors.append(f"{feature} mapping positions must be integers")
            continue
        if any(position < 0 or position >= 6 for position in positions):
            errors.append(f"{feature} mapping has an out-of-range position")
        if len(set(positions)) != len(positions):
            errors.append(f"{feature} mapping has duplicate source positions")
    return errors


def reorder_vectors(values: pa.ChunkedArray | pa.Array, mapping: dict[str, int]) -> pa.Array:
    positions = [mapping[name] for name in CANONICAL_JOINTS]
    rows = values.to_pylist()
    reordered = []
    for row in rows:
        if row is None or len(row) < 6:
            raise ValueError("joint vector must contain at least 6 positions")
        reordered.append([row[position] for position in positions])
    return pa.array(reordered, type=pa.list_(pa.float32(), 6))
