"""Blocking verification for a generated LeRobot v2.1 dataset."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any

import av
import pyarrow as pa
import pyarrow.parquet as pq


_REQUIRED_COLUMNS = (
    "action",
    "observation.state",
    "timestamp",
    "frame_index",
    "episode_index",
    "index",
    "task_index",
)
_INDEX_COLUMNS = ("frame_index", "episode_index", "index", "task_index")


@dataclass(frozen=True)
class VerificationError:
    category: str
    message: str
    path: str | None = None
    episode_index: int | None = None


@dataclass
class VerificationResult:
    errors: list[VerificationError] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": [asdict(error) for error in self.errors],
            "summary": dict(self.summary),
            "checks": dict(self.checks),
        }


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _plain(to_dict())
    return value


def _add_error(
    result: VerificationResult,
    category: str,
    message: str,
    *,
    path: Path | None = None,
    episode_index: int | None = None,
) -> None:
    result.errors.append(
        VerificationError(
            category=category,
            message=message,
            path=str(path) if path is not None else None,
            episode_index=episode_index,
        )
    )


def _read_json(
    path: Path, result: VerificationResult, *, required: bool = True
) -> dict[str, Any]:
    if not path.is_file():
        if required:
            _add_error(result, "metadata", f"missing required JSON file: {path.name}", path=path)
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        _add_error(result, "metadata", f"unreadable JSON file {path.name}: {exc}", path=path)
        return {}
    if not isinstance(value, dict):
        _add_error(result, "metadata", f"{path.name} must contain a JSON object", path=path)
        return {}
    return value


def _read_jsonl(path: Path, result: VerificationResult) -> list[dict[str, Any]]:
    if not path.is_file():
        _add_error(result, "metadata", f"missing required JSONL file: {path.name}", path=path)
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:
        _add_error(result, "metadata", f"unreadable JSONL file {path.name}: {exc}", path=path)
        return rows
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception as exc:
            _add_error(
                result,
                "metadata",
                f"invalid JSON in {path.name} line {line_number}: {exc}",
                path=path,
            )
            continue
        if not isinstance(row, dict):
            _add_error(
                result,
                "metadata",
                f"{path.name} line {line_number} must contain an object",
                path=path,
            )
            continue
        rows.append(row)
    return rows


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        converted = int(value)
    except (TypeError, ValueError):
        return None
    try:
        if float(value) != converted:
            return None
    except (TypeError, ValueError):
        pass
    return converted


def _episode_rows_by_index(
    rows: list[dict[str, Any]],
    result: VerificationResult,
    *,
    label: str,
    category: str,
) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    counts: Counter[int] = Counter()
    for row in rows:
        index = _integer(row.get("episode_index"))
        if index is None:
            _add_error(result, category, f"{label} contains an invalid episode_index")
            continue
        counts[index] += 1
        indexed.setdefault(index, row)
    for index, count in sorted(counts.items()):
        if count != 1:
            _add_error(
                result,
                category,
                f"{label} has duplicate episode_index {index}",
                episode_index=index,
            )
    actual = sorted(indexed)
    expected = list(range(len(rows)))
    if actual != expected:
        _add_error(
            result,
            category,
            f"{label} episode_index values are not contiguous: expected {expected}, got {actual}",
        )
    return indexed


def _task_catalog(
    rows: list[dict[str, Any]], result: VerificationResult
) -> tuple[dict[int, str], dict[str, int]]:
    by_index: dict[int, str] = {}
    by_prompt: dict[str, int] = {}
    for row in rows:
        index = _integer(row.get("task_index"))
        prompt = row.get("task")
        if index is None or not isinstance(prompt, str) or not prompt.strip():
            _add_error(result, "tasks", "tasks.jsonl has an invalid task reference")
            continue
        if index in by_index:
            _add_error(result, "tasks", f"duplicate task_index {index}")
            continue
        if prompt in by_prompt:
            _add_error(result, "tasks", f"duplicate task prompt {prompt!r}")
            continue
        by_index[index] = prompt
        by_prompt[prompt] = index
    expected = list(range(len(rows)))
    if sorted(by_index) != expected:
        _add_error(
            result,
            "tasks",
            f"task_index values are not contiguous: expected {expected}, got {sorted(by_index)}",
        )
    return by_index, by_prompt


def _manifest_episode_map(
    manifest: dict[str, Any], result: VerificationResult
) -> dict[int, dict[str, Any]]:
    raw = manifest.get("episodes", [])
    if not isinstance(raw, list):
        _add_error(result, "totals", "manifest episodes must be a list")
        return {}
    rows: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            row = dict(item)
        else:
            row = _plain(item)
        if not isinstance(row, dict):
            _add_error(result, "totals", "manifest contains an invalid episode")
            continue
        output_index = row.get("output_episode_index", row.get("episode_index"))
        row["episode_index"] = output_index
        rows.append(row)
    return _episode_rows_by_index(
        rows, result, label="manifest", category="totals"
    )


def _expected_camera_keys(
    info: dict[str, Any], manifest: dict[str, Any], result: VerificationResult
) -> list[str]:
    required = manifest.get("required_cameras", [])
    if not isinstance(required, list):
        required = []
    manifest_keys = [
        camera if str(camera).startswith("observation.images.") else f"observation.images.{camera}"
        for camera in required
        if str(camera).strip()
    ]
    features = info.get("features", {})
    if not isinstance(features, dict):
        features = {}
    metadata_keys = sorted(
        name
        for name, feature in features.items()
        if isinstance(feature, dict) and feature.get("dtype") == "video"
    )
    if len(metadata_keys) != 2:
        _add_error(
            result,
            "videos",
            f"metadata must declare exactly two video features; found {len(metadata_keys)}",
        )
    if manifest_keys and len(manifest_keys) != 2:
        _add_error(
            result,
            "videos",
            f"manifest must require exactly two cameras; found {len(manifest_keys)}",
        )
    if manifest_keys and sorted(manifest_keys) != metadata_keys:
        _add_error(
            result,
            "videos",
            "manifest cameras do not match metadata video features",
        )
    return manifest_keys if len(manifest_keys) == 2 else metadata_keys


def _field_vector_size(field: pa.Field) -> int | None:
    data_type = field.type
    if pa.types.is_fixed_size_list(data_type):
        return data_type.list_size
    return None


def _verify_schema(
    table: pa.Table,
    baseline: pa.Schema | None,
    info: dict[str, Any],
    result: VerificationResult,
    path: Path,
    episode_index: int,
) -> pa.Schema:
    missing = [name for name in _REQUIRED_COLUMNS if name not in table.column_names]
    if missing:
        _add_error(
            result,
            "schema",
            f"Parquet is missing required columns: {', '.join(missing)}",
            path=path,
            episode_index=episode_index,
        )
        return baseline or table.schema

    if baseline is not None and not table.schema.equals(baseline):
        changed = [
            name
            for name in set(baseline.names) & set(table.schema.names)
            if baseline.field(name).type != table.schema.field(name).type
        ]
        suffix = f": {', '.join(sorted(changed))}" if changed else ""
        _add_error(
            result,
            "schema",
            f"episode Parquet schema differs from the first episode{suffix}",
            path=path,
            episode_index=episode_index,
        )

    features = info.get("features", {})
    if not isinstance(features, dict):
        features = {}
    for name in ("action", "observation.state"):
        field = table.schema.field(name)
        data_type = field.type
        is_vector = (
            pa.types.is_list(data_type)
            or pa.types.is_large_list(data_type)
            or pa.types.is_fixed_size_list(data_type)
        )
        if not is_vector or data_type.value_type != pa.float32():
            _add_error(
                result,
                "schema",
                f"{name} must be a float32 vector, got {data_type}",
                path=path,
                episode_index=episode_index,
            )
            continue
        feature = features.get(name, {})
        expected_shape = feature.get("shape") if isinstance(feature, dict) else None
        expected_size = (
            _integer(expected_shape[0])
            if isinstance(expected_shape, list) and expected_shape
            else None
        )
        fixed_size = _field_vector_size(field)
        values = table[name].to_pylist()
        observed_sizes = {len(value) for value in values if value is not None}
        if expected_size is not None and (
            (fixed_size is not None and fixed_size != expected_size)
            or observed_sizes - {expected_size}
        ):
            _add_error(
                result,
                "schema",
                f"{name} vector size does not match metadata shape {expected_shape}",
                path=path,
                episode_index=episode_index,
            )
        if isinstance(feature, dict) and feature.get("dtype") != "float32":
            _add_error(
                result,
                "schema",
                f"{name} metadata dtype must be float32",
                path=path,
                episode_index=episode_index,
            )

    if table.schema.field("timestamp").type != pa.float32():
        _add_error(
            result,
            "schema",
            f"timestamp must be float32, got {table.schema.field('timestamp').type}",
            path=path,
            episode_index=episode_index,
        )
    for name in _INDEX_COLUMNS:
        if table.schema.field(name).type != pa.int64():
            _add_error(
                result,
                "schema",
                f"{name} must be int64, got {table.schema.field(name).type}",
                path=path,
                episode_index=episode_index,
            )
    return baseline or table.schema


def _verify_parquet(
    root: Path,
    info: dict[str, Any],
    episode_rows: dict[int, dict[str, Any]],
    manifest_rows: dict[int, dict[str, Any]],
    tasks: dict[int, str],
    task_prompts: dict[str, int],
    result: VerificationResult,
) -> dict[int, int]:
    frame_counts: dict[int, int] = {}
    expected_global_index = 0
    baseline: pa.Schema | None = None
    discovered = sorted(root.glob("data/chunk-*/episode_*.parquet"))
    if len(discovered) != len(episode_rows):
        _add_error(
            result,
            "totals",
            f"found {len(discovered)} episode Parquet files for {len(episode_rows)} metadata episodes",
        )

    fps = _integer(info.get("fps")) or 30
    for episode_index in sorted(episode_rows):
        path = (
            root
            / "data"
            / f"chunk-{episode_index // 1000:03d}"
            / f"episode_{episode_index:06d}.parquet"
        )
        if not path.is_file():
            _add_error(
                result,
                "totals",
                f"missing episode Parquet for episode {episode_index}",
                path=path,
                episode_index=episode_index,
            )
            continue
        try:
            table = pq.read_table(path)
        except Exception as exc:
            _add_error(
                result,
                "schema",
                f"unreadable episode Parquet: {exc}",
                path=path,
                episode_index=episode_index,
            )
            continue
        frame_counts[episode_index] = table.num_rows
        baseline = _verify_schema(
            table, baseline, info, result, path, episode_index
        )
        if any(name not in table.column_names for name in _REQUIRED_COLUMNS):
            expected_global_index += table.num_rows
            continue

        metadata_length = _integer(episode_rows[episode_index].get("length"))
        if metadata_length != table.num_rows:
            _add_error(
                result,
                "totals",
                f"episode {episode_index} metadata length {metadata_length} "
                f"does not match {table.num_rows} Parquet rows",
                path=path,
                episode_index=episode_index,
            )

        frame_values = table["frame_index"].to_pylist()
        expected_frames = list(range(table.num_rows))
        if frame_values != expected_frames:
            _add_error(
                result,
                "indices",
                f"episode {episode_index} frame_index is not contiguous: "
                f"expected {expected_frames}, got {frame_values}",
                path=path,
                episode_index=episode_index,
            )
        episode_values = table["episode_index"].to_pylist()
        if episode_values != [episode_index] * table.num_rows:
            _add_error(
                result,
                "indices",
                f"episode_index column for output episode {episode_index} "
                f"contains {sorted(set(episode_values))}",
                path=path,
                episode_index=episode_index,
            )
        global_values = table["index"].to_pylist()
        expected_globals = list(
            range(expected_global_index, expected_global_index + table.num_rows)
        )
        if global_values != expected_globals:
            _add_error(
                result,
                "indices",
                f"global index is not contiguous for episode {episode_index}: "
                f"expected {expected_globals}, got {global_values}",
                path=path,
                episode_index=episode_index,
            )

        metadata_prompts = episode_rows[episode_index].get("tasks")
        if not isinstance(metadata_prompts, list):
            metadata_prompts = []
        unknown_prompts = [
            prompt for prompt in metadata_prompts if prompt not in task_prompts
        ]
        if unknown_prompts:
            _add_error(
                result,
                "tasks",
                f"episode {episode_index} references unknown task prompts "
                f"{unknown_prompts}",
                episode_index=episode_index,
            )

        task_values = table["task_index"].to_pylist()
        unique_tasks = sorted(set(task_values))
        if len(unique_tasks) != 1 or unique_tasks[0] not in tasks:
            _add_error(
                result,
                "tasks",
                f"episode {episode_index} references unknown or mixed task_index "
                f"values {unique_tasks}",
                path=path,
                episode_index=episode_index,
            )
        else:
            task_index = unique_tasks[0]
            expected_prompt = tasks[task_index]
            if metadata_prompts != [expected_prompt]:
                _add_error(
                    result,
                    "tasks",
                    f"episode {episode_index} metadata tasks {metadata_prompts} "
                    f"do not match task_index {task_index} ({expected_prompt!r})",
                    episode_index=episode_index,
                )
            manifest_task = _integer(
                manifest_rows.get(episode_index, {}).get(
                    "output_task_index",
                    manifest_rows.get(episode_index, {}).get("task_index"),
                )
            )
            if manifest_task is not None and manifest_task != task_index:
                _add_error(
                    result,
                    "tasks",
                    f"episode {episode_index} task_index {task_index} does not "
                    f"match manifest output_task_index {manifest_task}",
                    episode_index=episode_index,
                )

        timestamps = table["timestamp"].to_pylist()
        expected_timestamps = [index / fps for index in range(table.num_rows)]
        if len(timestamps) != len(expected_timestamps) or any(
            not math.isclose(float(actual), expected, abs_tol=1e-5)
            for actual, expected in zip(timestamps, expected_timestamps)
        ):
            _add_error(
                result,
                "duration",
                f"episode {episode_index} timestamps do not match frame_index at {fps} FPS",
                path=path,
                episode_index=episode_index,
            )
        expected_global_index += table.num_rows
    return frame_counts


def _video_feature_expectations(
    info: dict[str, Any], camera_key: str, manifest: dict[str, Any]
) -> tuple[int, int, int, str]:
    features = info.get("features", {})
    feature = features.get(camera_key, {}) if isinstance(features, dict) else {}
    feature_info = feature.get("info", {}) if isinstance(feature, dict) else {}
    shape = feature.get("shape", []) if isinstance(feature, dict) else []
    width = (
        _integer(feature_info.get("video.width"))
        or (_integer(shape[1]) if isinstance(shape, list) and len(shape) > 1 else None)
        or _integer(manifest.get("width"))
        or 640
    )
    height = (
        _integer(feature_info.get("video.height"))
        or (_integer(shape[0]) if isinstance(shape, list) and shape else None)
        or _integer(manifest.get("height"))
        or 480
    )
    fps = (
        _integer(feature_info.get("video.fps"))
        or _integer(info.get("fps"))
        or _integer(manifest.get("fps"))
        or 30
    )
    pix_fmt = str(feature_info.get("video.pix_fmt") or "yuv420p")
    return width, height, fps, pix_fmt


def _verify_videos(
    root: Path,
    info: dict[str, Any],
    manifest: dict[str, Any],
    episode_rows: dict[int, dict[str, Any]],
    frame_counts: dict[int, int],
    camera_keys: list[str],
    result: VerificationResult,
) -> int:
    all_videos = sorted(root.glob("videos/chunk-*/*/episode_*.mp4"))
    for episode_index in sorted(episode_rows):
        episode_name = f"episode_{episode_index:06d}.mp4"
        actual = sorted(root.glob(f"videos/chunk-*/*/{episode_name}"))
        if len(actual) != 2:
            _add_error(
                result,
                "videos",
                f"episode {episode_index} must have exactly two video files; "
                f"found {len(actual)}",
                episode_index=episode_index,
            )
        expected_frames = frame_counts.get(
            episode_index, _integer(episode_rows[episode_index].get("length")) or 0
        )
        for camera_key in camera_keys:
            path = (
                root
                / "videos"
                / f"chunk-{episode_index // 1000:03d}"
                / camera_key
                / episode_name
            )
            if not path.is_file():
                _add_error(
                    result,
                    "videos",
                    f"missing video for episode {episode_index}, camera {camera_key}",
                    path=path,
                    episode_index=episode_index,
                )
                continue
            expected_width, expected_height, expected_fps, expected_pix_fmt = (
                _video_feature_expectations(info, camera_key, manifest)
            )
            try:
                with av.open(str(path)) as container:
                    if not container.streams.video:
                        raise ValueError("no video stream")
                    stream = container.streams.video[0]
                    frames = list(container.decode(stream))
                    average_rate = (
                        float(stream.average_rate) if stream.average_rate else 0.0
                    )
                    stream_duration = (
                        float(stream.duration * stream.time_base)
                        if stream.duration is not None and stream.time_base is not None
                        else None
                    )
            except Exception as exc:
                _add_error(
                    result,
                    "videos",
                    f"undecodable video for episode {episode_index}, "
                    f"camera {camera_key}: {exc}",
                    path=path,
                    episode_index=episode_index,
                )
                continue
            if not frames:
                _add_error(
                    result,
                    "videos",
                    f"undecodable video for episode {episode_index}, "
                    f"camera {camera_key}: no decoded frames",
                    path=path,
                    episode_index=episode_index,
                )
                continue
            if len(frames) != expected_frames:
                _add_error(
                    result,
                    "duration",
                    f"episode {episode_index}, camera {camera_key} has "
                    f"{len(frames)} decoded frames but {expected_frames} data frames",
                    path=path,
                    episode_index=episode_index,
                )
            expected_duration = expected_frames / expected_fps
            decoded_duration = len(frames) / expected_fps
            if not math.isclose(
                decoded_duration, expected_duration, abs_tol=1 / expected_fps
            ):
                _add_error(
                    result,
                    "duration",
                    f"episode {episode_index}, camera {camera_key} duration "
                    f"{decoded_duration:.6f}s does not match data duration "
                    f"{expected_duration:.6f}s",
                    path=path,
                    episode_index=episode_index,
                )
            if stream_duration is not None and not math.isclose(
                stream_duration, decoded_duration, abs_tol=1 / expected_fps
            ):
                _add_error(
                    result,
                    "duration",
                    f"episode {episode_index}, camera {camera_key} container "
                    f"duration {stream_duration:.6f}s does not match decoded "
                    f"duration {decoded_duration:.6f}s",
                    path=path,
                    episode_index=episode_index,
                )
            first = frames[0]
            if (first.width, first.height) != (expected_width, expected_height):
                _add_error(
                    result,
                    "schema",
                    f"video {camera_key} is {first.width}x{first.height}, expected "
                    f"{expected_width}x{expected_height}",
                    path=path,
                    episode_index=episode_index,
                )
            if first.format.name != expected_pix_fmt:
                _add_error(
                    result,
                    "schema",
                    f"video {camera_key} pixel format is {first.format.name}, "
                    f"expected {expected_pix_fmt}",
                    path=path,
                    episode_index=episode_index,
                )
            if not math.isclose(average_rate, expected_fps, abs_tol=0.01):
                _add_error(
                    result,
                    "duration",
                    f"video {camera_key} frame rate is {average_rate}, "
                    f"expected {expected_fps}",
                    path=path,
                    episode_index=episode_index,
                )
    return len(all_videos)


def _verify_provenance(
    rows: list[dict[str, Any]],
    episode_rows: dict[int, dict[str, Any]],
    manifest_rows: dict[int, dict[str, Any]],
    result: VerificationResult,
) -> None:
    indexed: dict[int, dict[str, Any]] = {}
    counts: Counter[int] = Counter()
    for row in rows:
        index = _integer(row.get("episode_index"))
        if index is None:
            _add_error(result, "provenance", "provenance has an invalid episode_index")
            continue
        counts[index] += 1
        indexed.setdefault(index, row)
    for index, count in sorted(counts.items()):
        if count > 1:
            _add_error(
                result,
                "provenance",
                f"duplicate provenance for episode {index}",
                episode_index=index,
            )
    expected = set(episode_rows)
    actual = set(indexed)
    for index in sorted(expected - actual):
        _add_error(
            result,
            "provenance",
            f"missing provenance for episode {index}",
            episode_index=index,
        )
    for index in sorted(actual - expected):
        _add_error(
            result,
            "provenance",
            f"provenance references unknown episode {index}",
            episode_index=index,
        )

    comparisons = {
        "source_dataset": ("source_dataset", "dataset_path"),
        "source_episode_index": ("source_episode_index",),
        "checkpoint_revision": ("checkpoint_revision",),
    }
    for index in sorted(expected & actual & set(manifest_rows)):
        provenance = indexed[index]
        manifest = manifest_rows[index]
        for provenance_key, manifest_keys in comparisons.items():
            expected_value = None
            for key in manifest_keys:
                if key in manifest:
                    expected_value = manifest[key]
                    break
            if expected_value is None:
                continue
            if provenance.get(provenance_key) != expected_value:
                _add_error(
                    result,
                    "provenance",
                    f"episode {index} provenance {provenance_key} "
                    f"{provenance.get(provenance_key)!r} does not match manifest "
                    f"{expected_value!r}",
                    episode_index=index,
                )


def _verify_totals(
    info: dict[str, Any],
    manifest: dict[str, Any],
    episode_rows: dict[int, dict[str, Any]],
    task_rows: list[dict[str, Any]],
    frame_counts: dict[int, int],
    video_count: int,
    result: VerificationResult,
) -> None:
    actual = {
        "total_episodes": len(episode_rows),
        "total_frames": sum(frame_counts.values()),
        "total_tasks": len(task_rows),
        "total_videos": video_count,
    }
    for key, value in actual.items():
        declared = _integer(info.get(key))
        if declared != value:
            _add_error(
                result,
                "totals",
                f"info.json {key} is {declared}, but verified output contains {value}",
            )
    metadata_frames = sum(
        _integer(row.get("length")) or 0 for row in episode_rows.values()
    )
    if metadata_frames != actual["total_frames"]:
        _add_error(
            result,
            "totals",
            f"episodes.jsonl lengths total {metadata_frames}, but Parquet contains "
            f"{actual['total_frames']} frames",
        )
    manifest_episodes = manifest.get("episodes", [])
    manifest_count = len(manifest_episodes) if isinstance(manifest_episodes, list) else 0
    if manifest_count != actual["total_episodes"]:
        _add_error(
            result,
            "totals",
            f"manifest contains {manifest_count} episodes, but verified output "
            f"contains {actual['total_episodes']}",
        )
    manifest_tasks = manifest.get("tasks", [])
    if isinstance(manifest_tasks, list) and len(manifest_tasks) != actual["total_tasks"]:
        _add_error(
            result,
            "totals",
            f"manifest contains {len(manifest_tasks)} tasks, but verified output "
            f"contains {actual['total_tasks']}",
        )


def verify_v21(path: str | Path, manifest: Any) -> VerificationResult:
    """Reopen and verify a staged LeRobot v2.1 export.

    All validation failures are returned as blocking structured errors. The
    function deliberately does not raise for malformed output so a background
    export job can persist and display every issue it can discover.
    """

    root = Path(path)
    result = VerificationResult()
    manifest_data = _plain(manifest)
    if not isinstance(manifest_data, dict):
        manifest_data = {}
        _add_error(result, "metadata", "manifest must be a mapping or dataclass")
    if not root.is_dir():
        _add_error(result, "metadata", f"export directory does not exist: {root}", path=root)
        result.checks = {"metadata": False}
        return result

    meta = root / "meta"
    info = _read_json(meta / "info.json", result)
    task_rows = _read_jsonl(meta / "tasks.jsonl", result)
    episode_list = _read_jsonl(meta / "episodes.jsonl", result)
    episode_stats = _read_jsonl(meta / "episodes_stats.jsonl", result)
    provenance = _read_jsonl(meta / "provenance.jsonl", result)
    _read_json(meta / "stats.json", result)

    if info.get("codebase_version") != "v2.1":
        _add_error(
            result,
            "metadata",
            f"codebase_version must be 'v2.1', got {info.get('codebase_version')!r}",
            path=meta / "info.json",
        )

    tasks, task_prompts = _task_catalog(task_rows, result)
    episode_rows = _episode_rows_by_index(
        episode_list, result, label="episodes.jsonl", category="indices"
    )
    stats_rows = _episode_rows_by_index(
        episode_stats, result, label="episodes_stats.jsonl", category="totals"
    )
    if set(stats_rows) != set(episode_rows):
        _add_error(
            result,
            "totals",
            "episodes_stats.jsonl does not cover every output episode exactly once",
        )
    manifest_rows = _manifest_episode_map(manifest_data, result)
    camera_keys = _expected_camera_keys(info, manifest_data, result)
    frame_counts = _verify_parquet(
        root,
        info,
        episode_rows,
        manifest_rows,
        tasks,
        task_prompts,
        result,
    )
    video_count = _verify_videos(
        root,
        info,
        manifest_data,
        episode_rows,
        frame_counts,
        camera_keys,
        result,
    )
    _verify_provenance(provenance, episode_rows, manifest_rows, result)
    _verify_totals(
        info,
        manifest_data,
        episode_rows,
        task_rows,
        frame_counts,
        video_count,
        result,
    )

    result.summary = {
        "episodes": len(episode_rows),
        "frames": sum(frame_counts.values()),
        "tasks": len(task_rows),
        "videos": video_count,
    }
    categories = {
        "metadata",
        "totals",
        "indices",
        "tasks",
        "schema",
        "videos",
        "duration",
        "provenance",
    }
    failed = {error.category for error in result.errors}
    result.checks = {category: category not in failed for category in sorted(categories)}
    return result
