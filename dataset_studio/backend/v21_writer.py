"""Write normalized Parquet data and metadata for a LeRobot v2.1 dataset.

Video encoding deliberately lives in :mod:`backend.video_export`; this module
only describes the two canonical video features in ``info.json``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .joint_mapping import CANONICAL_JOINTS, reorder_vectors


_MISSING = object()
_DATA_COLUMNS = ("action", "observation.state")
_INDEX_COLUMNS = (
    "timestamp",
    "frame_index",
    "episode_index",
    "index",
    "task_index",
)


@dataclass(frozen=True)
class EpisodeWriteResult:
    """The immutable record produced after writing one output episode."""

    episode_index: int
    task_index: int
    task: str
    length: int
    index_start: int
    next_index: int
    parquet_path: Path
    stats: dict[str, dict[str, list[Any]]]
    provenance: dict[str, Any]


def _value(obj: Any, *names: str, default: Any = _MISSING) -> Any:
    for name in names:
        if isinstance(obj, Mapping) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    if default is not _MISSING:
        return default
    raise ValueError(f"Missing required plan field: {' or '.join(names)}")


def _nested_value(obj: Any, *names: str, default: Any = _MISSING) -> Any:
    try:
        return _value(obj, *names)
    except ValueError:
        source = _value(obj, "source", default=None)
        if source is not None:
            return _value(source, *names, default=default)
        if default is not _MISSING:
            return default
        raise


def _resolve_source_path(plan_episode: Any, raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    source_dataset = _nested_value(
        plan_episode, "source_dataset", "dataset_path", default=None
    )
    return Path(source_dataset) / path if source_dataset else path


def _source_parquet_paths(plan_episode: Any) -> tuple[Path, ...]:
    raw_path = _nested_value(
        plan_episode,
        "source_parquet",
        "source_parquet_path",
        "parquet_path",
        "data_path",
        default=None,
    )
    if raw_path is not None:
        return (_resolve_source_path(plan_episode, raw_path),)
    raw_paths = _nested_value(plan_episode, "source_data_files", default=None)
    if not raw_paths:
        raise ValueError(
            "Missing required plan field: source_parquet or source_data_files"
        )
    return tuple(_resolve_source_path(plan_episode, path) for path in raw_paths)


def _float32_vector(column: pa.ChunkedArray, name: str) -> pa.Array:
    value_type = column.type
    if not (pa.types.is_list(value_type) or pa.types.is_fixed_size_list(value_type)):
        raise ValueError(f"{name} must be a list-valued column, got {value_type}")
    list_size = value_type.list_size if pa.types.is_fixed_size_list(value_type) else -1
    output_type = (
        pa.list_(pa.float32(), list_size) if list_size >= 0 else pa.list_(pa.float32())
    )
    try:
        return pa.array(column.to_pylist(), type=output_type)
    except (ArrowError, TypeError, ValueError) as error:
        raise ValueError(f"{name} cannot be cast to float32 vectors") from error


try:
    from pyarrow import ArrowException as ArrowError
except ImportError:  # PyArrow versions before ArrowException was exposed.
    ArrowError = pa.ArrowInvalid


def _slice_source_episode(
    table: pa.Table, plan_episode: Any, *, allow_empty: bool = False
) -> pa.Table:
    start = _nested_value(plan_episode, "source_row_start", "row_start", default=None)
    stop = _nested_value(plan_episode, "source_row_end", "row_end", default=None)
    if start is not None or stop is not None:
        start = int(start or 0)
        stop = table.num_rows if stop is None else int(stop)
        table = table.slice(start, max(0, stop - start))

    source_episode_index = _nested_value(
        plan_episode, "source_episode_index", "episode_index", default=None
    )
    if source_episode_index is not None and "episode_index" in table.column_names:
        table = table.filter(
            pc.equal(table["episode_index"], pa.scalar(int(source_episode_index)))
        )
    if table.num_rows == 0 and not allow_empty:
        raise ValueError(
            f"Source episode {source_episode_index!r} has no rows in its Parquet file"
        )
    return table


def _read_source_episode(plan_episode: Any) -> tuple[pa.Table, tuple[Path, ...]]:
    source_paths = _source_parquet_paths(plan_episode)
    source_episode_index = _nested_value(
        plan_episode, "source_episode_index", "episode_index", default=None
    )
    has_row_slice = (
        _nested_value(plan_episode, "source_row_start", "row_start", default=None) is not None
        or _nested_value(plan_episode, "source_row_end", "row_end", default=None) is not None
    )
    matching_tables: list[pa.Table] = []
    matching_paths: list[Path] = []
    for source_path in source_paths:
        if not source_path.is_file():
            raise FileNotFoundError(f"Source Parquet does not exist: {source_path}")
        if source_episode_index is not None and not has_row_slice:
            try:
                table = pq.read_table(
                    source_path,
                    filters=[("episode_index", "=", int(source_episode_index))],
                )
            except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
                table = pq.read_table(source_path)
        else:
            table = pq.read_table(source_path)
        table = _slice_source_episode(
            table, plan_episode, allow_empty=True
        )
        if table.num_rows:
            matching_tables.append(table)
            matching_paths.append(source_path)
    if not matching_tables:
        raise ValueError(
            f"Source episode {source_episode_index!r} has no rows in its Parquet files"
        )
    if len(matching_tables) == 1:
        return matching_tables[0], tuple(matching_paths)
    return pa.concat_tables(matching_tables), tuple(matching_paths)


def _column_stats(column: pa.ChunkedArray | pa.Array) -> dict[str, list[Any]]:
    values = np.asarray(column.to_pylist())
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    if values.ndim != 2 or values.shape[0] == 0:
        raise ValueError("Cannot calculate statistics for an empty or ragged column")

    is_integer = np.issubdtype(values.dtype, np.integer)

    def serialise(items: np.ndarray, preserve_integer: bool = False) -> list[Any]:
        if preserve_integer and is_integer:
            return [int(item) for item in items]
        return [float(item) for item in items]

    return {
        "min": serialise(values.min(axis=0), preserve_integer=True),
        "max": serialise(values.max(axis=0), preserve_integer=True),
        "mean": serialise(values.mean(axis=0)),
        "std": serialise(values.std(axis=0)),
        "count": [int(values.shape[0])],
    }


def _table_stats(table: pa.Table) -> dict[str, dict[str, list[Any]]]:
    return {name: _column_stats(table[name]) for name in table.column_names}


def write_episode_data(
    plan_episode: Any, output_index_start: int, destination: str | Path
) -> EpisodeWriteResult:
    """Slice one source episode, rebuild its indices, and write v2.1 Parquet."""

    source, source_paths = _read_source_episode(plan_episode)
    missing = [name for name in _DATA_COLUMNS if name not in source.column_names]
    if missing:
        raise ValueError(f"Source Parquet is missing columns: {', '.join(missing)}")

    episode_index = int(
        _value(plan_episode, "output_episode_index", "output_index")
    )
    task_index = int(_value(plan_episode, "task_index", "output_task_index"))
    task = str(
        _value(
            plan_episode,
            "final_prompt",
            "edited_prompt",
            "task",
            "prompt",
            default="",
        )
    )
    fps = float(_value(plan_episode, "fps", default=30))
    if fps <= 0:
        raise ValueError("fps must be greater than zero")
    row_count = source.num_rows
    frame_indices = np.arange(row_count, dtype=np.int64)
    global_indices = np.arange(
        int(output_index_start), int(output_index_start) + row_count, dtype=np.int64
    )

    joint_mapping = _value(plan_episode, "joint_mapping", default={})
    action_mapping = joint_mapping.get("action") if isinstance(joint_mapping, Mapping) else None
    state_mapping = joint_mapping.get("observation.state") if isinstance(joint_mapping, Mapping) else None
    action = reorder_vectors(source["action"], action_mapping) if action_mapping else _float32_vector(source["action"], "action")
    state = reorder_vectors(source["observation.state"], state_mapping) if state_mapping else _float32_vector(source["observation.state"], "observation.state")

    table = pa.table(
        {
            "action": action,
            "observation.state": state,
            "timestamp": pa.array(frame_indices / fps, type=pa.float32()),
            "frame_index": pa.array(frame_indices, type=pa.int64()),
            "episode_index": pa.array(
                np.full(row_count, episode_index, dtype=np.int64), type=pa.int64()
            ),
            "index": pa.array(global_indices, type=pa.int64()),
            "task_index": pa.array(
                np.full(row_count, task_index, dtype=np.int64), type=pa.int64()
            ),
        }
    )

    destination = Path(destination)
    parquet_path = (
        destination
        / "data"
        / f"chunk-{episode_index // 1000:03d}"
        / f"episode_{episode_index:06d}.parquet"
    )
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, parquet_path)

    source_episode_index = _nested_value(
        plan_episode, "source_episode_index", "episode_index", default=None
    )
    source_dataset = _nested_value(
        plan_episode, "source_dataset", "dataset_path", default=None
    )
    provenance = {
        "episode_index": episode_index,
        "task_index": task_index,
        "task": task,
        "source_dataset": str(source_dataset) if source_dataset is not None else None,
        "source_episode_index": (
            int(source_episode_index) if source_episode_index is not None else None
        ),
        "source_parquet": (
            str(source_paths[0])
            if len(source_paths) == 1
            else [str(path) for path in source_paths]
        ),
        "checkpoint_revision": _value(
            plan_episode, "checkpoint_revision", "revision", default=None
        ),
        "updated_by": _value(plan_episode, "updated_by", default=None),
        "camera_mapping": _camera_mapping(plan_episode),
        "joint_mapping": json.loads(json.dumps(joint_mapping)),
        "flags": list(_value(plan_episode, "flags", default=[])),
    }
    return EpisodeWriteResult(
        episode_index=episode_index,
        task_index=task_index,
        task=task,
        length=row_count,
        index_start=int(output_index_start),
        next_index=int(output_index_start) + row_count,
        parquet_path=parquet_path,
        stats=_table_stats(table),
        provenance=provenance,
    )


def _camera_mapping(plan_episode: Any) -> dict[str, str | None]:
    cameras = _value(plan_episode, "camera_mapping", "cameras", default={})
    if isinstance(cameras, Mapping):
        return {
            str(source): (str(target) if target is not None else None)
            for source, target in cameras.items()
        }
    mapping = {}
    for camera in cameras:
        canonical = _value(camera, "canonical_name", "canonical")
        source = _value(camera, "source_camera", "source")
        mapping[str(canonical)] = str(source)
    return mapping


def _normalise_tasks(plan: Any, results: Sequence[EpisodeWriteResult]) -> list[dict]:
    raw_tasks = _value(plan, "tasks", default=None)
    if raw_tasks is None:
        by_index = {result.task_index: result.task for result in results}
        return [
            {"task_index": index, "task": by_index[index]}
            for index in sorted(by_index)
        ]
    if isinstance(raw_tasks, Mapping):
        return [
            {"task_index": int(index), "task": str(task)}
            for index, task in sorted(raw_tasks.items(), key=lambda item: int(item[0]))
        ]

    tasks = []
    for position, raw_task in enumerate(raw_tasks):
        if isinstance(raw_task, str):
            tasks.append({"task_index": position, "task": raw_task})
        else:
            tasks.append(
                {
                    "task_index": int(
                        _value(raw_task, "task_index", "index", default=position)
                    ),
                    "task": str(
                        _value(raw_task, "task", "prompt", "final_prompt")
                    ),
                }
            )
    return sorted(tasks, key=lambda item: item["task_index"])


def _aggregate_stats(
    results: Sequence[EpisodeWriteResult],
) -> dict[str, dict[str, list[Any]]]:
    if not results:
        return {}
    aggregate: dict[str, dict[str, list[Any]]] = {}
    for name in results[0].stats:
        rows = [result.stats[name] for result in results]
        counts = np.asarray([row["count"][0] for row in rows], dtype=np.float64)
        total = int(counts.sum())
        means = np.asarray([row["mean"] for row in rows], dtype=np.float64)
        variances = np.square(
            np.asarray([row["std"] for row in rows], dtype=np.float64)
        )
        mean = np.sum(means * counts[:, None], axis=0) / total
        variance = np.sum(
            counts[:, None] * (variances + np.square(means - mean)), axis=0
        ) / total
        aggregate[name] = {
            "min": np.min(
                np.asarray([row["min"] for row in rows]), axis=0
            ).tolist(),
            "max": np.max(
                np.asarray([row["max"] for row in rows]), axis=0
            ).tolist(),
            "mean": mean.tolist(),
            "std": np.sqrt(variance).tolist(),
            "count": [total],
        }
    return aggregate


def _schema_feature(
    plan: Any,
    name: str,
    results: Sequence[EpisodeWriteResult],
) -> dict[str, Any]:
    schemas = _value(plan, "schemas", "schema", default={})
    schema = schemas.get(name, {}) if isinstance(schemas, Mapping) else {}
    shape = _value(schema, "shape", default=None)
    names = _value(schema, "names", default=None)
    if shape is None and results:
        arrow_type = pq.read_schema(results[0].parquet_path).field(name).type
        shape = [arrow_type.list_size] if pa.types.is_fixed_size_list(arrow_type) else []
    has_joint_mapping = any(result.provenance.get("joint_mapping") for result in results)
    if has_joint_mapping:
        shape = [6]
        names = list(CANONICAL_JOINTS)
    return {
        "dtype": "float32",
        "shape": list(shape or []),
        "names": list(names) if names is not None else None,
    }


def _video_feature(fps: float, width: int, height: int) -> dict[str, Any]:
    return {
        "dtype": "video",
        "shape": [height, width, 3],
        "names": ["height", "width", "channels"],
        "info": {
            "video.fps": fps,
            "video.height": height,
            "video.width": width,
            "video.channels": 3,
            "video.codec": "h264",
            "video.pix_fmt": "yuv420p",
            "video.is_depth_map": False,
            "has_audio": False,
        },
    }


def _index_feature(dtype: str) -> dict[str, Any]:
    return {"dtype": dtype, "shape": [1], "names": None}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=4, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(
                json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
            )


def _second_camera(plan: Any, settings: Any) -> str:
    configured = _value(
        settings, "second_camera", "secondary_camera", default=None
    )
    if configured:
        return str(configured)
    required = _value(plan, "required_cameras", default=[])
    for camera in required:
        if str(camera) != "wrist":
            return str(camera)
    return "front"


def finalize_metadata(
    plan: Any,
    results: Sequence[EpisodeWriteResult],
    destination: str | Path,
) -> dict[str, Path]:
    """Regenerate all v2.1 metadata after episode Parquet files are written."""

    destination = Path(destination)
    meta = destination / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    ordered_results = sorted(results, key=lambda result: result.episode_index)
    tasks = _normalise_tasks(plan, ordered_results)

    settings = _value(plan, "settings", default={})
    fps = float(
        _value(plan, "fps", default=_value(settings, "fps", default=30))
    )
    second_camera = str(
        _value(
            plan,
            "second_camera",
            "secondary_camera",
            default=_second_camera(plan, settings),
        )
    )
    resolution = _value(
        plan,
        "resolution",
        "video_size",
        default=_value(settings, "resolution", "video_size", default=(640, 480)),
    )
    if isinstance(resolution, Mapping):
        width = int(
            _value(
                plan,
                "width",
                default=_value(resolution, "width", default=640),
            )
        )
        height = int(
            _value(
                plan,
                "height",
                default=_value(resolution, "height", default=480),
            )
        )
    else:
        default_width, default_height = (int(value) for value in resolution)
        width = int(_value(plan, "width", default=default_width))
        height = int(_value(plan, "height", default=default_height))
    robot_type = str(
        _value(
            plan,
            "robot_type",
            default=_value(settings, "robot_type", default="so101_follower"),
        )
    )

    features = {
        "action": _schema_feature(plan, "action", ordered_results),
        "observation.state": _schema_feature(
            plan, "observation.state", ordered_results
        ),
        "observation.images.wrist": _video_feature(fps, width, height),
        f"observation.images.{second_camera}": _video_feature(
            fps, width, height
        ),
        "timestamp": _index_feature("float32"),
        "frame_index": _index_feature("int64"),
        "episode_index": _index_feature("int64"),
        "index": _index_feature("int64"),
        "task_index": _index_feature("int64"),
    }
    episode_count = len(ordered_results)
    info = {
        "codebase_version": "v2.1",
        "robot_type": robot_type,
        "total_episodes": episode_count,
        "total_frames": sum(result.length for result in ordered_results),
        "total_tasks": len(tasks),
        "total_videos": episode_count * 2,
        "total_chunks": math.ceil(episode_count / 1000) if episode_count else 0,
        "chunks_size": 1000,
        "fps": fps,
        "splits": {"train": f"0:{episode_count}"},
        "data_path": (
            "data/chunk-{episode_chunk:03d}/"
            "episode_{episode_index:06d}.parquet"
        ),
        "video_path": (
            "videos/chunk-{episode_chunk:03d}/{video_key}/"
            "episode_{episode_index:06d}.mp4"
        ),
        "features": features,
    }

    paths = {
        "info": meta / "info.json",
        "tasks": meta / "tasks.jsonl",
        "episodes": meta / "episodes.jsonl",
        "episode_stats": meta / "episodes_stats.jsonl",
        "stats": meta / "stats.json",
        "provenance": meta / "provenance.jsonl",
    }
    _write_json(paths["info"], info)
    _write_jsonl(paths["tasks"], tasks)
    _write_jsonl(
        paths["episodes"],
        (
            {
                "episode_index": result.episode_index,
                "tasks": [result.task],
                "length": result.length,
            }
            for result in ordered_results
        ),
    )
    _write_jsonl(
        paths["episode_stats"],
        (
            {"episode_index": result.episode_index, "stats": result.stats}
            for result in ordered_results
        ),
    )
    _write_json(paths["stats"], _aggregate_stats(ordered_results))
    _write_jsonl(paths["provenance"], (result.provenance for result in ordered_results))
    return paths
