from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .catalog import Dataset


@dataclass(frozen=True)
class EpisodeChoice:
    dataset_path: str
    episode_index: int
    final_prompt: str


@dataclass
class ValidationResult:
    choices: list[EpisodeChoice] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    task_counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_and_balance(
    catalog: list[Dataset],
    choices: list[EpisodeChoice],
    camera_mappings: dict[str, dict[str, str | None]],
    required_cameras: list[str],
    max_per_task: int | None,
) -> ValidationResult:
    result = ValidationResult()
    datasets = {dataset.path: dataset for dataset in catalog}

    for choice in choices:
        dataset = datasets.get(choice.dataset_path)
        if dataset is None:
            result.errors.append(f"unknown dataset: {choice.dataset_path}")
            continue
        if not dataset.valid:
            result.errors.append(f"dataset is invalid: {dataset.name}")
            continue
        episode = next((item for item in dataset.episodes if item.index == choice.episode_index), None)
        if episode is None:
            result.errors.append(f"episode {choice.episode_index} does not exist in {dataset.name}")
            continue
        if episode.exclusion_reason:
            result.errors.append(f"episode {choice.episode_index} in {dataset.name}: {episode.exclusion_reason}")
        if not choice.final_prompt.strip():
            result.errors.append(f"episode {choice.episode_index} in {dataset.name} has an empty final prompt")

    for dataset_path in {choice.dataset_path for choice in choices if choice.dataset_path in datasets}:
        mapping = camera_mappings.get(dataset_path, {})
        mapped = {target for target in mapping.values() if target}
        for camera in required_cameras:
            if camera not in mapped:
                result.errors.append(f"{datasets[dataset_path].name} is missing a mapping for required camera '{camera}'")

    if result.errors:
        return result

    counts: Counter[str] = Counter()
    for choice in choices:
        if max_per_task is None or counts[choice.final_prompt] < max_per_task:
            result.choices.append(choice)
            counts[choice.final_prompt] += 1
    result.task_counts = dict(counts)
    return result
