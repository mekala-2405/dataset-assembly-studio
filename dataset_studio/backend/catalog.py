from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pyarrow.parquet as pq


DERIVED_MARKERS = ("merged", "redundant")
MIN_DURATION_SECONDS = 2.0


@dataclass
class Task:
    index: int
    prompt: str


@dataclass
class Episode:
    index: int
    task_index: int
    duration_seconds: float
    exclusion_reason: str | None = None
    video_files: dict[str, str] = field(default_factory=dict)
    video_starts: dict[str, float] = field(default_factory=dict)
    data_files: list[str] = field(default_factory=list)


@dataclass
class Dataset:
    path: str
    name: str
    version: str | None
    fps: float
    cameras: list[str]
    tasks: list[Task]
    episodes: list[Episode] = field(default_factory=list)
    valid: bool = True
    issues: list[str] = field(default_factory=list)
    derived: bool = False

    @property
    def usable_episodes(self) -> int:
        return sum(episode.exclusion_reason is None for episode in self.episodes)


def _parquet_rows(path: Path) -> int:
    return pq.ParquetFile(path).metadata.num_rows


def _find_episode_files(dataset_root: Path) -> list[Path]:
    return sorted((dataset_root / "meta" / "episodes").rglob("*.parquet"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _read_metadata(dataset_root: Path) -> tuple[list[dict], list[dict]]:
    episode_files = _find_episode_files(dataset_root)
    task_file = dataset_root / "meta" / "tasks.parquet"
    if episode_files:
        return (
            pq.read_table(episode_files).to_pylist(),
            pq.read_table(task_file).to_pylist() if task_file.exists() else [],
        )

    episode_file = dataset_root / "meta" / "episodes.jsonl"
    task_file = dataset_root / "meta" / "tasks.jsonl"
    if not episode_file.exists():
        raise ValueError("missing episode metadata")
    return _read_jsonl(episode_file), _read_jsonl(task_file) if task_file.exists() else []


def _task_index_for_episode(row: dict, tasks: list[Task]) -> int:
    if "task_index" in row:
        return int(row["task_index"])
    prompts = row.get("tasks") or []
    if not prompts:
        raise ValueError("episode is missing task metadata")
    prompt = str(prompts[0])
    for task in tasks:
        if task.prompt == prompt:
            return task.index
    index = max((task.index for task in tasks), default=-1) + 1
    tasks.append(Task(index=index, prompt=prompt))
    return index


def _task_from_row(row: dict) -> Task:
    prompt = row.get("task", row.get("__index_level_0__"))
    if prompt is None:
        raise ValueError("task metadata is missing prompt")
    return Task(int(row["task_index"]), str(prompt))


def _episode_video_references(dataset_root: Path, cameras: list[str], row: dict) -> tuple[dict[str, str], dict[str, float]]:
    files: dict[str, str] = {}
    starts: dict[str, float] = {}
    for camera in cameras:
        prefix = f"videos/{camera}"
        chunk = row.get(f"{prefix}/chunk_index")
        file_index = row.get(f"{prefix}/file_index")
        if chunk is None or file_index is None:
            episode_index = int(row["episode_index"])
            chunk_index = episode_index // 1000
            direct = dataset_root / "videos" / f"chunk-{chunk_index:03d}" / camera / f"episode_{episode_index:06d}.mp4"
            if direct.is_file():
                files[camera] = str(direct)
                starts[camera] = 0.0
            continue
        matches = sorted((dataset_root / "videos" / camera).glob(f"chunk-{int(chunk):03d}/file-{int(file_index):03d}.*"))
        if matches:
            files[camera] = str(matches[0])
            starts[camera] = float(row.get(f"{prefix}/from_timestamp", 0.0))
    return files, starts


def _episode_data_references(dataset_root: Path, row: dict, all_data_files: list[Path]) -> list[str]:
    chunk = row.get("data/chunk_index")
    file_index = row.get("data/file_index")
    if chunk is not None and file_index is not None:
        matches = sorted((dataset_root / "data" / f"chunk-{int(chunk):03d}").glob(f"file-{int(file_index):03d}.parquet"))
        if matches:
            return [str(matches[0])]
    episode_index = int(row["episode_index"])
    direct = dataset_root / "data" / f"chunk-{episode_index // 1000:03d}" / f"episode_{episode_index:06d}.parquet"
    if direct.is_file():
        return [str(direct)]
    return [str(path) for path in all_data_files]


def scan_catalog(root: Path) -> list[Dataset]:
    catalog: list[Dataset] = []
    for info_path in root.rglob("meta/info.json"):
        dataset_root = info_path.parent.parent
        info = json.loads(info_path.read_text())
        features = info.get("features", {})
        dataset = Dataset(
            path=str(dataset_root),
            name=str(dataset_root.relative_to(root)),
            version=info.get("codebase_version"),
            fps=float(info.get("fps", 0)),
            cameras=[name for name, value in features.items() if value.get("dtype") == "video"],
            tasks=[],
            derived=any(marker in dataset_root.name.lower() for marker in DERIVED_MARKERS),
        )
        try:
            if len(dataset.cameras) < 2:
                raise ValueError("fewer than two video cameras")
            data_files = sorted((dataset_root / "data").rglob("*.parquet"))
            if not data_files:
                raise ValueError("missing data parquet files")
            for parquet_file in data_files:
                _parquet_rows(parquet_file)
            episode_table, task_table = _read_metadata(dataset_root)
            dataset.tasks = [_task_from_row(row) for row in task_table]
            for row in episode_table:
                length = int(row["length"])
                duration = length / dataset.fps
                reason = "shorter than 2 seconds" if duration < MIN_DURATION_SECONDS else None
                files, starts = _episode_video_references(dataset_root, dataset.cameras, row)
                episode_data = _episode_data_references(dataset_root, row, data_files)
                dataset.episodes.append(Episode(int(row["episode_index"]), _task_index_for_episode(row, dataset.tasks), duration, reason, files, starts, episode_data))
            declared_episode_count = int(info["total_episodes"])
            metadata_episode_count = len(episode_table)
            if metadata_episode_count != declared_episode_count:
                row_label = "row" if metadata_episode_count == 1 else "rows"
                raise ValueError(
                    "episode count does not match metadata: "
                    f"info.json declares {declared_episode_count}, but episode metadata "
                    f"contains {metadata_episode_count} {row_label}"
                )
            if sum(_parquet_rows(path) for path in data_files) != int(info["total_frames"]):
                raise ValueError("frame count does not match metadata")
        except Exception as exc:
            dataset.valid = False
            message = str(exc)
            dataset.issues.append("invalid parquet" if "Parquet" in message or "parquet" in message else message)
        catalog.append(dataset)
    return catalog
