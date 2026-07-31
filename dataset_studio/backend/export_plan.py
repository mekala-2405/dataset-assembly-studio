from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from .catalog import Dataset, Episode
from .joint_mapping import build_joint_contract, validate_joint_mapping


@dataclass(frozen=True)
class PlanError:
    dataset_path: str
    checkpoint_revision: int | None
    category: str
    message: str
    phase: str


@dataclass(frozen=True)
class CameraSource:
    canonical_name: str
    source_camera: str
    video_path: str
    start_seconds: float


@dataclass(frozen=True)
class PlanEpisode:
    dataset_path: str
    dataset_name: str
    source_episode_index: int
    source_fps: float
    duration_seconds: float
    final_prompt: str
    checkpoint_revision: int
    updated_by: str
    output_episode_index: int
    output_task_index: int
    source_data_files: tuple[str, ...]
    cameras: tuple[CameraSource, ...]
    joint_mapping: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class ExportPlan:
    output_path: str
    required_cameras: list[str]
    fps: int = 30
    width: int = 640
    height: int = 480
    codec: str = "h264"
    max_per_task: int | None = None
    episodes: list[PlanEpisode] = field(default_factory=list)
    errors: list[PlanError] = field(default_factory=list)
    selected_task_counts: dict[str, int] = field(default_factory=dict)
    retained_task_counts: dict[str, int] = field(default_factory=dict)
    task_group_caps: dict[str, int] = field(default_factory=dict)
    task_group_names: dict[str, str | None] = field(default_factory=dict)
    selected_group_counts: dict[str, int] = field(default_factory=dict)
    retained_group_counts: dict[str, int] = field(default_factory=dict)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    schemas: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return asdict(self) | {"ok": self.ok}


@dataclass
class _Candidate:
    dataset: Dataset
    episode: Episode
    final_prompt: str
    revision: int
    updated_by: str
    data_files: tuple[str, ...]
    cameras: tuple[CameraSource, ...]
    schema: dict[str, Any]
    joint_mapping: dict[str, dict[str, int]]


def _error(
    plan: ExportPlan,
    dataset_path: str,
    revision: int | None,
    category: str,
    message: str,
    phase: str,
) -> None:
    plan.errors.append(PlanError(dataset_path, revision, category, message, phase))


def _data_schema(dataset: Dataset) -> tuple[tuple[str, ...], dict[str, Any], str | None]:
    files = tuple(str(path) for path in sorted(Path(dataset.path).joinpath("data").rglob("*.parquet")))
    if not files:
        return files, {}, "missing source Parquet data"
    info_path = Path(dataset.path) / "meta" / "info.json"
    try:
        features = json.loads(info_path.read_text()).get("features", {}) if info_path.exists() else {}
    except (OSError, json.JSONDecodeError) as exc:
        return files, {}, f"unreadable source feature metadata: {exc}"
    expected: dict[str, Any] | None = None
    for filename in files:
        try:
            schema = pq.ParquetFile(filename).schema_arrow
        except Exception as exc:
            return files, {}, f"unreadable source Parquet '{filename}': {exc}"
        names = set(schema.names)
        missing = {"action", "observation.state", "episode_index"} - names
        if missing:
            return files, {}, f"source Parquet is missing required columns: {', '.join(sorted(missing))}"
        current = {
            name: {
                "arrow_type": str(schema.field(name).type),
                "shape": features.get(name, {}).get("shape"),
                "names": features.get(name, {}).get("names"),
            }
            for name in ("action", "observation.state")
        }
        if expected is None:
            expected = current
        elif current != expected:
            return files, current, "action or observation.state schema changes between source Parquet files"
    return files, expected or {}, None


def _camera_sources(
    mapping: dict,
    required: list[str],
    episode: Episode,
) -> tuple[tuple[CameraSource, ...], list[str]]:
    cameras: list[CameraSource] = []
    errors: list[str] = []
    for canonical in required:
        matches = sorted(source for source, target in mapping.items() if target == canonical)
        if len(matches) != 1:
            errors.append(f"missing a unique mapping for required camera '{canonical}'")
            continue
        source = matches[0]
        video = episode.video_files.get(source)
        if not video:
            errors.append(f"episode {episode.index} has no video for required camera '{canonical}' ({source})")
            continue
        path = Path(video)
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"episode {episode.index} has unreadable video for required camera '{canonical}': {video}")
            continue
        cameras.append(
            CameraSource(
                canonical_name=canonical,
                source_camera=source,
                video_path=str(path),
                start_seconds=float(episode.video_starts.get(source, 0.0)),
            )
        )
    return tuple(cameras), errors


def build_export_plan(
    catalog: list[Dataset],
    shared: dict,
    settings: dict,
    output_path: str | Path,
    task_group_policy: dict | None = None,
) -> ExportPlan:
    second = str(settings.get("second_camera", "")).strip()
    required = ["wrist", second] if second and second != "wrist" else ["wrist"]
    cap_value = settings.get("max_per_task")
    cap = int(cap_value) if cap_value not in (None, "") else None
    plan = ExportPlan(
        output_path=str(output_path),
        required_cameras=required,
        max_per_task=cap,
        fps=30,
        width=640,
        height=480,
        codec="h264",
    )
    destination = Path(output_path)
    if destination.exists():
        _error(plan, "", None, "output", f"output destination already exists: {destination}", "output")
    if not second or second == "wrist":
        _error(plan, "", None, "camera", "choose exactly one non-wrist second camera", "output")
    if cap is not None and cap < 1:
        _error(plan, "", None, "balance", "maximum episodes per task must be at least 1", "balance")

    prompt_groups: dict[str, str] = {}
    group_caps: dict[str, int] = {}
    for group_id, group in sorted((task_group_policy or {}).get("groups", {}).items()):
        if not isinstance(group_id, str) or not isinstance(group, dict):
            _error(plan, "", None, "balance", "task group policy is malformed", "balance")
            continue
        group_name = group.get("name")
        plan.task_group_names[group_id] = str(group_name) if group_name else None
        group_cap = group.get("episode_cap")
        if isinstance(group_cap, bool) or (
            group_cap is not None
            and (not isinstance(group_cap, int) or group_cap < 0)
        ):
            _error(plan, "", None, "balance", f"task group {group_id} has an invalid episode cap", "balance")
        elif group_cap is not None:
            group_caps[group_id] = group_cap
        for prompt in group.get("prompts") or []:
            prompt = str(prompt)
            existing = prompt_groups.get(prompt)
            if existing is not None and existing != group_id:
                _error(
                    plan,
                    "",
                    None,
                    "balance",
                    f"task prompt belongs to multiple groups: {prompt}",
                    "balance",
                )
                continue
            prompt_groups[prompt] = group_id
    plan.task_group_caps = dict(sorted(group_caps.items()))

    datasets = {dataset.path: dataset for dataset in catalog}
    candidates: list[_Candidate] = []
    seen: set[tuple[str, int]] = set()
    schema_cache: dict[str, tuple[tuple[str, ...], dict[str, str], str | None]] = {}
    contract_cache = {}
    validated_mappings: set[tuple[str, str]] = set()

    checkpoints = shared.get("checkpoints", {})
    for checkpoint_path, checkpoint in sorted(checkpoints.items()):
        if checkpoint.get("status") != "approved":
            continue
        recipe = checkpoint.get("recipe") or {}
        revision = int(checkpoint.get("revision", 0))
        updated_by = str(checkpoint.get("updated_by", "unknown"))
        mapping = recipe.get("camera_mapping") or {}
        joint_mapping = recipe.get("joint_mapping") or {}
        checkpoint_choices = recipe.get("choices") or []
        if not checkpoint_choices:
            _error(
                plan,
                checkpoint_path,
                revision,
                "selection",
                "approved checkpoint has no selected episodes; select episodes or mark the dataset excluded",
                "episodes",
            )
        for raw_choice in checkpoint_choices:
            dataset_path = str(raw_choice.get("dataset_path") or checkpoint_path)
            episode_index = raw_choice.get("episode_index")
            dataset = datasets.get(dataset_path)
            if dataset is None:
                _error(plan, dataset_path, revision, "source", f"unknown approved dataset: {dataset_path}", "sources")
                continue
            if not dataset.valid:
                _error(plan, dataset_path, revision, "source", f"approved dataset is invalid: {dataset.name}", "sources")
            if dataset.fps != 30:
                _error(
                    plan,
                    dataset_path,
                    revision,
                    "schema",
                    f"{dataset.name} uses {dataset.fps:g} FPS; export requires 30 FPS",
                    "preflight",
                )
            try:
                episode_index = int(episode_index)
            except (TypeError, ValueError):
                _error(plan, dataset_path, revision, "episode", "choice has an invalid episode index", "episodes")
                continue
            key = (dataset_path, episode_index)
            if key in seen:
                _error(
                    plan,
                    dataset_path,
                    revision,
                    "duplicate",
                    f"duplicate approved source episode: {dataset.name} episode {episode_index}",
                    "episodes",
                )
                continue
            seen.add(key)
            episode = next((item for item in dataset.episodes if item.index == episode_index), None)
            if episode is None:
                _error(plan, dataset_path, revision, "episode", f"episode {episode_index} does not exist", "episodes")
                continue
            prompt = str(raw_choice.get("final_prompt", ""))
            if not prompt.strip():
                _error(plan, dataset_path, revision, "prompt", f"episode {episode_index} has an empty final prompt", "episodes")
            if episode.duration_seconds < 2 or episode.exclusion_reason:
                reason = episode.exclusion_reason or "shorter than 2 seconds"
                _error(plan, dataset_path, revision, "duration", f"episode {episode_index}: {reason}", "episodes")

            camera_sources, camera_errors = _camera_sources(mapping, required, episode)
            for message in camera_errors:
                _error(plan, dataset_path, revision, "camera", message, "cameras")

            if dataset.path not in schema_cache:
                schema_cache[dataset.path] = _data_schema(dataset)
            if dataset.path not in contract_cache:
                try:
                    contract_cache[dataset.path] = build_joint_contract(Path(dataset.path))
                except Exception as exc:
                    _error(plan, dataset.path, revision, "joints", f"joint metadata is unreadable: {exc}", "joints")
                    contract_cache[dataset.path] = None
            validation_key = (checkpoint_path, dataset.path)
            contract = contract_cache[dataset.path]
            if validation_key not in validated_mappings and contract is not None:
                for message in validate_joint_mapping(joint_mapping, contract):
                    _error(plan, dataset.path, revision, "joints", message, "joints")
                validated_mappings.add(validation_key)
            data_files, schema, schema_error = schema_cache[dataset.path]
            if schema_error:
                _error(plan, dataset_path, revision, "schema", schema_error, "preflight")
            candidates.append(
                _Candidate(
                    dataset=dataset,
                    episode=episode,
                    final_prompt=prompt.strip(),
                    revision=revision,
                    updated_by=updated_by,
                    data_files=tuple(episode.data_files) or data_files,
                    cameras=camera_sources,
                    schema=schema,
                    joint_mapping=json.loads(json.dumps(joint_mapping)),
                )
            )

    selected_counts = Counter(candidate.final_prompt for candidate in candidates if candidate.final_prompt)
    plan.selected_task_counts = dict(sorted(selected_counts.items()))
    selected_group_counts = Counter(
        prompt_groups[candidate.final_prompt]
        for candidate in candidates
        if candidate.final_prompt in prompt_groups
    )
    plan.selected_group_counts = dict(sorted(selected_group_counts.items()))

    schema_baseline: dict[str, Any] | None = None
    for candidate in sorted(candidates, key=lambda item: (item.dataset.path, item.episode.index)):
        if not candidate.schema:
            continue
        if schema_baseline is None:
            schema_baseline = candidate.schema
            plan.schemas = dict(schema_baseline)
        elif candidate.schema != schema_baseline:
            for column in ("action", "observation.state"):
                current = candidate.schema.get(column) or {}
                baseline = schema_baseline.get(column) or {}
                if current.get("arrow_type") != baseline.get("arrow_type") or current.get("shape") != baseline.get("shape"):
                    _error(
                        plan,
                        candidate.dataset.path,
                        candidate.revision,
                        "schema",
                        f"{column} schema {candidate.schema.get(column)} does not match {schema_baseline.get(column)}",
                        "preflight",
                    )

    task_kept: list[_Candidate] = []
    task_retained_counts: Counter[str] = Counter()
    for candidate in sorted(candidates, key=lambda item: (item.dataset.path, item.episode.index)):
        if cap is None or task_retained_counts[candidate.final_prompt] < cap:
            task_kept.append(candidate)
            task_retained_counts[candidate.final_prompt] += 1

    kept: list[_Candidate] = []
    retained_group_counts: Counter[str] = Counter()
    for candidate in task_kept:
        group_id = prompt_groups.get(candidate.final_prompt)
        group_cap = group_caps.get(group_id) if group_id is not None else None
        if group_cap is not None and retained_group_counts[group_id] >= group_cap:
            continue
        kept.append(candidate)
        if group_id is not None:
            retained_group_counts[group_id] += 1

    retained_counts = Counter(candidate.final_prompt for candidate in kept)
    plan.retained_task_counts = dict(sorted(retained_counts.items()))
    plan.retained_group_counts = {
        group_id: retained_group_counts.get(group_id, 0)
        for group_id in sorted(selected_group_counts)
    }

    task_indexes: dict[str, int] = {}
    for candidate in kept:
        if candidate.final_prompt not in task_indexes:
            task_indexes[candidate.final_prompt] = len(task_indexes)
    plan.tasks = [
        {"task_index": task_index, "task": prompt}
        for prompt, task_index in task_indexes.items()
    ]
    plan.episodes = [
        PlanEpisode(
            dataset_path=candidate.dataset.path,
            dataset_name=candidate.dataset.name,
            source_episode_index=candidate.episode.index,
            source_fps=candidate.dataset.fps,
            duration_seconds=candidate.episode.duration_seconds,
            final_prompt=candidate.final_prompt,
            checkpoint_revision=candidate.revision,
            updated_by=candidate.updated_by,
            output_episode_index=output_index,
            output_task_index=task_indexes[candidate.final_prompt],
            source_data_files=candidate.data_files,
            cameras=candidate.cameras,
            joint_mapping=candidate.joint_mapping,
        )
        for output_index, candidate in enumerate(kept)
    ]
    if not plan.episodes:
        _error(plan, "", None, "selection", "no approved episodes are available for export", "sources")
    return plan
