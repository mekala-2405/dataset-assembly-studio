import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from backend.export_plan import CameraSource, ExportPlan, PlanEpisode
from backend.joint_mapping import CANONICAL_JOINTS
from backend.v21_writer import finalize_metadata, write_episode_data


def _json_lines(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class V21WriterTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = self.root / "source.parquet"
        self.destination = self.root / "output"

        vector_type = pa.list_(pa.float32(), 2)
        table = pa.table(
            {
                "action": pa.array(
                    [[90.0, 91.0], [1.0, 3.0], [5.0, 7.0], [80.0, 81.0]],
                    type=vector_type,
                ),
                "observation.state": pa.array(
                    [[190.0, 191.0], [2.0, 4.0], [6.0, 8.0], [180.0, 181.0]],
                    type=vector_type,
                ),
                "timestamp": pa.array([9.0, 4.0, 8.0, 12.0], type=pa.float64()),
                "frame_index": pa.array([9, 30, 31, 12], type=pa.int32()),
                "episode_index": pa.array([4, 7, 7, 8], type=pa.int32()),
                "index": pa.array([90, 91, 92, 93], type=pa.int32()),
                "task_index": pa.array([8, 8, 8, 8], type=pa.int32()),
            }
        )
        pq.write_table(table, self.source)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_write_episode_slices_and_reindexes_rows(self):
        episode = {
            "source_parquet": str(self.source),
            "source_dataset": "/datasets/source-one",
            "source_episode_index": 7,
            "output_episode_index": 2,
            "task_index": 3,
            "final_prompt": "Place the cube",
            "camera_mapping": {"wrist": "wrist_left", "front": "desk_view"},
            "checkpoint_revision": 12,
            "flags": ["clean", "preferred"],
        }

        result = write_episode_data(episode, 10, self.destination)

        expected_path = (
            self.destination / "data/chunk-000/episode_000002.parquet"
        )
        self.assertEqual(expected_path, result.parquet_path)
        output = pq.read_table(expected_path)
        self.assertEqual([[1.0, 3.0], [5.0, 7.0]], output["action"].to_pylist())
        self.assertEqual(
            [[2.0, 4.0], [6.0, 8.0]],
            output["observation.state"].to_pylist(),
        )
        self.assertEqual(0.0, output["timestamp"][0].as_py())
        self.assertAlmostEqual(1.0 / 30.0, output["timestamp"][1].as_py())
        self.assertEqual([0, 1], output["frame_index"].to_pylist())
        self.assertEqual([2, 2], output["episode_index"].to_pylist())
        self.assertEqual([10, 11], output["index"].to_pylist())
        self.assertEqual([3, 3], output["task_index"].to_pylist())
        self.assertEqual(pa.float32(), output.schema.field("timestamp").type)
        for name in ("frame_index", "episode_index", "index", "task_index"):
            self.assertEqual(pa.int64(), output.schema.field(name).type)
        self.assertEqual(pa.float32(), output.schema.field("action").type.value_type)
        self.assertEqual(
            pa.float32(), output.schema.field("observation.state").type.value_type
        )
        self.assertEqual(2, result.length)
        self.assertEqual(12, result.next_index)
        self.assertEqual([1.0, 3.0], result.stats["action"]["min"])
        self.assertEqual([5.0, 7.0], result.stats["action"]["max"])
        self.assertEqual([3.0, 5.0], result.stats["action"]["mean"])
        self.assertEqual([2], result.stats["action"]["count"])

    def test_write_episode_uses_v21_chunk_number(self):
        result = write_episode_data(
            {
                "source_parquet": self.source,
                "source_episode_index": 7,
                "output_episode_index": 1001,
                "task_index": 0,
                "final_prompt": "Place the cube",
            },
            0,
            self.destination,
        )

        self.assertEqual(
            self.destination / "data/chunk-001/episode_001001.parquet",
            result.parquet_path,
        )

    def test_finalize_metadata_regenerates_complete_v21_catalog(self):
        first = write_episode_data(
            {
                "source_parquet": self.source,
                "source_dataset": "/datasets/source-one",
                "source_episode_index": 7,
                "output_episode_index": 0,
                "task_index": 1,
                "final_prompt": "Place the cube",
                "camera_mapping": {"wrist": "wrist_left", "front": "desk_view"},
                "checkpoint_revision": 12,
                "flags": ["preferred"],
            },
            0,
            self.destination,
        )
        second_source = self.root / "second.parquet"
        vector_type = pa.list_(pa.float32(), 2)
        pq.write_table(
            pa.table(
                {
                    "action": pa.array([[9.0, 11.0]], type=vector_type),
                    "observation.state": pa.array([[10.0, 12.0]], type=vector_type),
                    "timestamp": pa.array([99.0]),
                    "frame_index": pa.array([99]),
                    "episode_index": pa.array([4]),
                    "index": pa.array([99]),
                    "task_index": pa.array([99]),
                }
            ),
            second_source,
        )
        second = write_episode_data(
            {
                "source_parquet": second_source,
                "source_dataset": "/datasets/source-two",
                "source_episode_index": 4,
                "output_episode_index": 1,
                "task_index": 0,
                "final_prompt": "Lift the cup",
                "camera_mapping": {"wrist": "wrist", "front": "front"},
                "checkpoint_revision": 3,
                "flags": [],
            },
            first.next_index,
            self.destination,
        )
        plan = {
            "fps": 30,
            "robot_type": "so101_follower",
            "second_camera": "front",
            "tasks": [
                {"task_index": 0, "task": "Lift the cup"},
                {"task_index": 1, "task": "Place the cube"},
            ],
            "schemas": {
                "action": {
                    "shape": [2],
                    "names": ["joint_a", "joint_b"],
                },
                "observation.state": {
                    "shape": [2],
                    "names": ["joint_a", "joint_b"],
                },
            },
        }

        paths = finalize_metadata(plan, [first, second], self.destination)

        meta = self.destination / "meta"
        self.assertEqual(
            {
                "info",
                "tasks",
                "episodes",
                "episode_stats",
                "stats",
                "provenance",
            },
            set(paths),
        )
        self.assertEqual(
            [
                {"task_index": 0, "task": "Lift the cup"},
                {"task_index": 1, "task": "Place the cube"},
            ],
            _json_lines(meta / "tasks.jsonl"),
        )
        self.assertEqual(
            [
                {
                    "episode_index": 0,
                    "tasks": ["Place the cube"],
                    "length": 2,
                },
                {
                    "episode_index": 1,
                    "tasks": ["Lift the cup"],
                    "length": 1,
                },
            ],
            _json_lines(meta / "episodes.jsonl"),
        )
        episode_stats = _json_lines(meta / "episodes_stats.jsonl")
        self.assertEqual([0, 1], [row["episode_index"] for row in episode_stats])
        self.assertEqual([2], episode_stats[0]["stats"]["index"]["count"])

        info = json.loads((meta / "info.json").read_text(encoding="utf-8"))
        self.assertEqual("v2.1", info["codebase_version"])
        self.assertEqual(2, info["total_episodes"])
        self.assertEqual(3, info["total_frames"])
        self.assertEqual(2, info["total_tasks"])
        self.assertEqual(4, info["total_videos"])
        self.assertEqual("0:2", info["splits"]["train"])
        self.assertEqual(
            "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
            info["data_path"],
        )
        self.assertEqual(
            "videos/chunk-{episode_chunk:03d}/{video_key}/"
            "episode_{episode_index:06d}.mp4",
            info["video_path"],
        )
        self.assertEqual(
            {
                "observation.images.wrist",
                "observation.images.front",
            },
            {
                name
                for name, feature in info["features"].items()
                if feature["dtype"] == "video"
            },
        )
        self.assertEqual(
            ["joint_a", "joint_b"], info["features"]["action"]["names"]
        )

        aggregate = json.loads((meta / "stats.json").read_text(encoding="utf-8"))
        self.assertEqual([1.0, 3.0], aggregate["action"]["min"])
        self.assertEqual([9.0, 11.0], aggregate["action"]["max"])
        self.assertEqual([5.0, 7.0], aggregate["action"]["mean"])
        self.assertEqual([3], aggregate["action"]["count"])

        provenance = _json_lines(meta / "provenance.jsonl")
        self.assertEqual([0, 1], [row["episode_index"] for row in provenance])
        self.assertEqual("/datasets/source-one", provenance[0]["source_dataset"])
        self.assertEqual(7, provenance[0]["source_episode_index"])
        self.assertEqual(12, provenance[0]["checkpoint_revision"])
        self.assertEqual(
            {"wrist": "wrist_left", "front": "desk_view"},
            provenance[0]["camera_mapping"],
        )
        self.assertEqual(["preferred"], provenance[0]["flags"])

    def test_accepts_the_export_planners_typed_episode_contract(self):
        unrelated = self.root / "unrelated.parquet"
        pq.write_table(
            pq.read_table(self.source).filter(
                pc.equal(
                    pq.read_table(self.source)["episode_index"], pa.scalar(4)
                )
            ),
            unrelated,
        )
        episode = PlanEpisode(
            dataset_path="/datasets/planned",
            dataset_name="planned",
            source_episode_index=7,
            source_fps=30,
            duration_seconds=2.0,
            final_prompt="Place the cube",
            checkpoint_revision=5,
            updated_by="alice",
            output_episode_index=0,
            output_task_index=0,
            source_data_files=(str(unrelated), str(self.source)),
            cameras=(
                CameraSource("wrist", "wrist_left", "/video/wrist.mp4", 0.0),
                CameraSource("front", "desk_view", "/video/front.mp4", 0.0),
            ),
            joint_mapping={},
        )

        result = write_episode_data(episode, 0, self.destination)
        plan = ExportPlan(
            output_path=str(self.destination),
            required_cameras=["wrist", "front"],
            width=320,
            height=240,
            episodes=[episode],
            tasks=[{"task_index": 0, "task": "Place the cube"}],
            schemas={
                "action": "fixed_size_list<element: float>[2]",
                "observation.state": "fixed_size_list<element: float>[2]",
            },
        )
        finalize_metadata(plan, [result], self.destination)

        self.assertEqual(2, result.length)
        self.assertEqual(
            {"wrist": "wrist_left", "front": "desk_view"},
            result.provenance["camera_mapping"],
        )
        self.assertEqual("alice", result.provenance["updated_by"])
        info = json.loads(
            (self.destination / "meta/info.json").read_text(encoding="utf-8")
        )
        self.assertIn("observation.images.front", info["features"])
        self.assertEqual(
            [240, 320, 3], info["features"]["observation.images.front"]["shape"]
        )

    def test_reorders_action_and_state_using_frozen_joint_mapping(self):
        source = self.root / "six.parquet"
        vector_type = pa.list_(pa.float32(), 6)
        pq.write_table(
            pa.table(
                {
                    "action": pa.array([[1, 2, 3, 4, 5, 6]], type=vector_type),
                    "observation.state": pa.array([[10, 20, 30, 40, 50, 60]], type=vector_type),
                    "episode_index": pa.array([0], type=pa.int64()),
                }
            ),
            source,
        )
        reverse = {name: 5 - index for index, name in enumerate(CANONICAL_JOINTS)}
        identity = {name: index for index, name in enumerate(CANONICAL_JOINTS)}
        episode = {
            "source_parquet": source,
            "source_episode_index": 0,
            "output_episode_index": 0,
            "task_index": 0,
            "final_prompt": "Move",
            "joint_mapping": {"action": reverse, "observation.state": identity},
        }

        result = write_episode_data(episode, 0, self.destination)
        table = pq.read_table(result.parquet_path)
        self.assertEqual(table["action"].to_pylist(), [[6, 5, 4, 3, 2, 1]])
        self.assertEqual(table["observation.state"].to_pylist(), [[10, 20, 30, 40, 50, 60]])
        finalize_metadata(
            {"tasks": [{"task_index": 0, "task": "Move"}], "required_cameras": ["wrist", "front"]},
            [result],
            self.destination,
        )
        info = json.loads((self.destination / "meta/info.json").read_text())
        self.assertEqual(info["features"]["action"]["names"], list(CANONICAL_JOINTS))
        self.assertEqual(info["features"]["observation.state"]["names"], list(CANONICAL_JOINTS))


if __name__ == "__main__":
    unittest.main()
