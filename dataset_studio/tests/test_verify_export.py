from __future__ import annotations

import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from backend.verify_export import _timestamp_matches, verify_v21


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_video(path: Path, frame_count: int = 3, fps: int = 30) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width = 64
        stream.height = 48
        stream.pix_fmt = "yuv420p"
        for index in range(frame_count):
            pixels = np.full((48, 64, 3), 20 + index, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = index
            frame.time_base = Fraction(1, fps)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _episode_table(
    episode_index: int,
    first_global_index: int,
    task_index: int,
    *,
    frame_indexes: list[int] | None = None,
    vector_size: int = 2,
) -> pa.Table:
    frames = frame_indexes or [0, 1, 2]
    length = len(frames)
    vector_type = pa.list_(pa.float32(), vector_size)
    vectors = [[float(row + column) for column in range(vector_size)] for row in range(length)]
    return pa.table(
        {
            "action": pa.array(vectors, type=vector_type),
            "observation.state": pa.array(vectors, type=vector_type),
            "timestamp": pa.array([index / 30 for index in range(length)], type=pa.float32()),
            "frame_index": pa.array(frames, type=pa.int64()),
            "episode_index": pa.array([episode_index] * length, type=pa.int64()),
            "index": pa.array(
                list(range(first_global_index, first_global_index + length)),
                type=pa.int64(),
            ),
            "task_index": pa.array([task_index] * length, type=pa.int64()),
        }
    )


class ExportFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.meta = root / "meta"
        self.tasks = [
            {"task_index": 0, "task": "Pick cube"},
            {"task_index": 1, "task": "Place cube"},
        ]
        self.episodes = [
            {"episode_index": 0, "tasks": ["Pick cube"], "length": 3},
            {"episode_index": 1, "tasks": ["Place cube"], "length": 3},
        ]
        self.provenance = [
            {
                "episode_index": 0,
                "source_dataset": "/source/a",
                "source_episode_index": 4,
                "checkpoint_revision": 2,
            },
            {
                "episode_index": 1,
                "source_dataset": "/source/b",
                "source_episode_index": 8,
                "checkpoint_revision": 5,
            },
        ]
        self.info = {
            "codebase_version": "v2.1",
            "fps": 30,
            "total_episodes": 2,
            "total_frames": 6,
            "total_tasks": 2,
            "total_videos": 4,
            "chunks_size": 1000,
            "data_path": (
                "data/chunk-{episode_chunk:03d}/"
                "episode_{episode_index:06d}.parquet"
            ),
            "video_path": (
                "videos/chunk-{episode_chunk:03d}/{video_key}/"
                "episode_{episode_index:06d}.mp4"
            ),
            "features": {
                "action": {"dtype": "float32", "shape": [2], "names": ["a", "b"]},
                "observation.state": {
                    "dtype": "float32",
                    "shape": [2],
                    "names": ["a", "b"],
                },
                "timestamp": {"dtype": "float32", "shape": [1], "names": None},
                "frame_index": {"dtype": "int64", "shape": [1], "names": None},
                "episode_index": {"dtype": "int64", "shape": [1], "names": None},
                "index": {"dtype": "int64", "shape": [1], "names": None},
                "task_index": {"dtype": "int64", "shape": [1], "names": None},
                "observation.images.wrist": {
                    "dtype": "video",
                    "shape": [48, 64, 3],
                    "info": {
                        "video.fps": 30,
                        "video.height": 48,
                        "video.width": 64,
                        "video.pix_fmt": "yuv420p",
                    },
                },
                "observation.images.front": {
                    "dtype": "video",
                    "shape": [48, 64, 3],
                    "info": {
                        "video.fps": 30,
                        "video.height": 48,
                        "video.width": 64,
                        "video.pix_fmt": "yuv420p",
                    },
                },
            },
        }
        self.manifest = {
            "fps": 30,
            "width": 64,
            "height": 48,
            "required_cameras": ["wrist", "front"],
            "tasks": self.tasks,
            "episodes": [
                {
                    "output_episode_index": 0,
                    "output_task_index": 0,
                    "dataset_path": "/source/a",
                    "source_episode_index": 4,
                    "checkpoint_revision": 2,
                },
                {
                    "output_episode_index": 1,
                    "output_task_index": 1,
                    "dataset_path": "/source/b",
                    "source_episode_index": 8,
                    "checkpoint_revision": 5,
                },
            ],
        }
        self.write()

    def write(self) -> None:
        self.meta.mkdir(parents=True, exist_ok=True)
        (self.meta / "info.json").write_text(
            json.dumps(self.info, sort_keys=True), encoding="utf-8"
        )
        _write_jsonl(self.meta / "tasks.jsonl", self.tasks)
        _write_jsonl(self.meta / "episodes.jsonl", self.episodes)
        _write_jsonl(self.meta / "provenance.jsonl", self.provenance)
        _write_jsonl(
            self.meta / "episodes_stats.jsonl",
            [
                {"episode_index": 0, "stats": {"index": {"count": [3]}}},
                {"episode_index": 1, "stats": {"index": {"count": [3]}}},
            ],
        )
        (self.meta / "stats.json").write_text("{}", encoding="utf-8")

        for episode_index, task_index in enumerate((0, 1)):
            parquet = (
                self.root
                / "data"
                / "chunk-000"
                / f"episode_{episode_index:06d}.parquet"
            )
            parquet.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(
                _episode_table(
                    episode_index,
                    first_global_index=episode_index * 3,
                    task_index=task_index,
                ),
                parquet,
            )
            for camera in ("observation.images.wrist", "observation.images.front"):
                _write_video(
                    self.root
                    / "videos"
                    / "chunk-000"
                    / camera
                    / f"episode_{episode_index:06d}.mp4"
                )

    def rewrite_info(self) -> None:
        (self.meta / "info.json").write_text(
            json.dumps(self.info, sort_keys=True), encoding="utf-8"
        )


def _categories(result) -> set[str]:
    return {error.category for error in result.errors}


class VerifyV21Tests(unittest.TestCase):
    def test_accepts_complete_consistent_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ExportFixture(Path(tmp))

            result = verify_v21(fixture.root, fixture.manifest)

            self.assertTrue(result.ok)
            self.assertEqual([], result.errors)
            self.assertEqual(
                {
                    "episodes": 2,
                    "frames": 6,
                    "tasks": 2,
                    "videos": 4,
                },
                result.summary,
            )
            self.assertTrue(result.to_dict()["ok"])

    def test_blocks_metadata_and_manifest_total_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ExportFixture(Path(tmp))
            fixture.info["total_frames"] = 7
            fixture.rewrite_info()
            fixture.manifest["episodes"].pop()

            result = verify_v21(fixture.root, fixture.manifest)

            self.assertFalse(result.ok)
            self.assertIn("totals", _categories(result))
            messages = "\n".join(error.message for error in result.errors)
            self.assertIn("total_frames", messages)
            self.assertIn("manifest", messages)

    def test_blocks_noncontiguous_episode_frame_and_global_indices(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ExportFixture(Path(tmp))
            broken_path = (
                fixture.root / "data/chunk-000/episode_000001.parquet"
            )
            broken = _episode_table(
                episode_index=2,
                first_global_index=4,
                task_index=1,
                frame_indexes=[0, 2, 3],
            )
            pq.write_table(broken, broken_path)

            result = verify_v21(fixture.root, fixture.manifest)

            self.assertIn("indices", _categories(result))
            messages = "\n".join(error.message for error in result.errors)
            self.assertIn("episode_index", messages)
            self.assertIn("frame_index", messages)
            self.assertIn("global index", messages)

    def test_blocks_unknown_or_inconsistent_task_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ExportFixture(Path(tmp))
            broken_path = (
                fixture.root / "data/chunk-000/episode_000001.parquet"
            )
            pq.write_table(
                _episode_table(1, first_global_index=3, task_index=99),
                broken_path,
            )
            fixture.episodes[1]["tasks"] = ["Unknown task"]
            _write_jsonl(fixture.meta / "episodes.jsonl", fixture.episodes)

            result = verify_v21(fixture.root, fixture.manifest)

            self.assertIn("tasks", _categories(result))
            messages = "\n".join(error.message for error in result.errors)
            self.assertIn("99", messages)
            self.assertIn("Unknown task", messages)

    def test_accepts_float32_rounding_for_long_episode_timestamps(self):
        frame_index = 15364
        stored = np.float32(frame_index / 30)

        self.assertTrue(_timestamp_matches(stored, frame_index, 30))
        self.assertFalse(_timestamp_matches(float(stored) + 0.001, frame_index, 30))

    def test_blocks_missing_extra_and_undecodable_videos(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ExportFixture(Path(tmp))
            (
                fixture.root
                / "videos/chunk-000/observation.images.front/episode_000000.mp4"
            ).unlink()
            corrupt = (
                fixture.root
                / "videos/chunk-000/observation.images.front/episode_000001.mp4"
            )
            corrupt.write_bytes(b"not an mp4")
            _write_video(
                fixture.root
                / "videos/chunk-000/observation.images.top/episode_000001.mp4"
            )

            result = verify_v21(fixture.root, fixture.manifest)

            self.assertIn("videos", _categories(result))
            messages = "\n".join(error.message for error in result.errors)
            self.assertIn("exactly two", messages)
            self.assertIn("undecodable", messages)

    def test_blocks_schema_changes_and_metadata_schema_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ExportFixture(Path(tmp))
            broken_path = (
                fixture.root / "data/chunk-000/episode_000001.parquet"
            )
            pq.write_table(
                _episode_table(
                    1,
                    first_global_index=3,
                    task_index=1,
                    vector_size=3,
                ),
                broken_path,
            )

            result = verify_v21(fixture.root, fixture.manifest)

            self.assertIn("schema", _categories(result))
            self.assertTrue(
                any("action" in error.message for error in result.errors)
            )

    def test_blocks_video_frame_and_duration_disagreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ExportFixture(Path(tmp))
            video = (
                fixture.root
                / "videos/chunk-000/observation.images.front/episode_000001.mp4"
            )
            _write_video(video, frame_count=2)

            result = verify_v21(fixture.root, fixture.manifest)

            self.assertIn("duration", _categories(result))
            messages = "\n".join(error.message for error in result.errors)
            self.assertIn("2 decoded frames", messages)
            self.assertIn("3 data frames", messages)

    def test_blocks_missing_duplicate_and_manifest_mismatched_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = ExportFixture(Path(tmp))
            fixture.provenance = [
                fixture.provenance[0],
                dict(fixture.provenance[0]),
            ]
            _write_jsonl(fixture.meta / "provenance.jsonl", fixture.provenance)
            fixture.manifest["episodes"][0]["checkpoint_revision"] = 77

            result = verify_v21(fixture.root, fixture.manifest)

            self.assertIn("provenance", _categories(result))
            messages = "\n".join(error.message for error in result.errors)
            self.assertIn("duplicate", messages)
            self.assertIn("missing provenance", messages)
            self.assertIn("checkpoint_revision", messages)


if __name__ == "__main__":
    unittest.main()
