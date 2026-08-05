import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backend.catalog import scan_catalog


def write_dataset(root: Path, name: str, *, valid=True, duration=3.0, derived=False):
    dataset = root / name
    (dataset / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    (dataset / "data" / "chunk-000").mkdir(parents=True)
    (dataset / "videos" / "observation.images.front" / "chunk-000").mkdir(parents=True)
    (dataset / "videos" / "observation.images.top" / "chunk-000").mkdir(parents=True)
    info = {
        "codebase_version": "v3.0",
        "robot_type": "so101_follower",
        "total_episodes": 1,
        "total_frames": int(duration * 30),
        "total_tasks": 1,
        "fps": 30,
        "features": {
            "action": {"dtype": "float32", "shape": [6]},
            "observation.state": {"dtype": "float32", "shape": [6]},
            "observation.images.front": {"dtype": "video", "shape": [480, 640, 3]},
            "observation.images.top": {"dtype": "video", "shape": [480, 640, 3]},
        },
    }
    (dataset / "meta" / "info.json").write_text(json.dumps(info))
    pq.write_table(pa.table({"episode_index": [0], "length": [int(duration * 30)], "task_index": [0]}), dataset / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    pq.write_table(pa.table({"frame_index": list(range(int(duration * 30)))}), dataset / "data" / "chunk-000" / "file-000.parquet")
    pq.write_table(pa.table({"task_index": [0], "task": ["Sort blocks"]}), dataset / "meta" / "tasks.parquet")
    (dataset / "videos" / "observation.images.front" / "chunk-000" / "file-000.mp4").write_bytes(b"video")
    (dataset / "videos" / "observation.images.top" / "chunk-000" / "file-000.mp4").write_bytes(b"video")
    if not valid:
        (dataset / "data" / "chunk-000" / "file-000.parquet").write_bytes(b"not parquet")
    return dataset


class CatalogTests(unittest.TestCase):
    def test_reads_v21_jsonl_episode_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "v21"
            (dataset / "meta").mkdir(parents=True)
            (dataset / "data" / "chunk-000").mkdir(parents=True)
            (dataset / "videos" / "chunk-000" / "front").mkdir(parents=True)
            (dataset / "videos" / "chunk-000" / "top").mkdir(parents=True)
            (dataset / "meta" / "info.json").write_text(json.dumps({"codebase_version": "v2.1", "fps": 30, "total_episodes": 1, "total_frames": 90, "features": {"front": {"dtype": "video"}, "top": {"dtype": "video"}}}))
            (dataset / "meta" / "tasks.jsonl").write_text('{"task_index": 0, "task": "Fold cloth"}\n')
            (dataset / "meta" / "episodes.jsonl").write_text('{"episode_index": 0, "length": 90, "task_index": 0}\n')
            pq.write_table(pa.table({"frame_index": list(range(90))}), dataset / "data" / "chunk-000" / "file-000.parquet")
            front_video = dataset / "videos" / "chunk-000" / "front" / "episode_000000.mp4"
            top_video = dataset / "videos" / "chunk-000" / "top" / "episode_000000.mp4"
            front_video.write_bytes(b"video")
            top_video.write_bytes(b"video")

            catalog = scan_catalog(root)

            self.assertTrue(catalog[0].valid)
            self.assertEqual(catalog[0].usable_episodes, 1)
            self.assertEqual(catalog[0].tasks[0].prompt, "Fold cloth")
            self.assertEqual(catalog[0].episodes[0].video_files["front"], str(front_video))
            self.assertEqual(catalog[0].episodes[0].video_starts["front"], 0.0)

    def test_discovers_nested_valid_dataset_and_marks_derived_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, "nested/prior_merged")

            catalog = scan_catalog(root)

            self.assertEqual(len(catalog), 1)
            self.assertTrue(catalog[0].derived)
            self.assertEqual(catalog[0].usable_episodes, 1)
            self.assertEqual(catalog[0].tasks[0].prompt, "Sort blocks")
            self.assertEqual(
                catalog[0].episodes[0].data_files,
                [str(Path(catalog[0].path) / "data/chunk-000/file-000.parquet")],
            )

    def test_reads_v3_episode_tasks_list_without_task_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root, "v3-tasks-list")
            pq.write_table(
                pa.table({"episode_index": [0], "length": [90], "tasks": [["Sort blocks"]]}),
                dataset / "meta" / "episodes" / "chunk-000" / "file-000.parquet",
            )

            catalog = scan_catalog(root)

            self.assertTrue(catalog[0].valid)
            self.assertEqual(catalog[0].episodes[0].task_index, 0)

    def test_reads_task_prompt_stored_in_parquet_index_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root, "index-column-task")
            pq.write_table(
                pa.table({"task_index": [0], "__index_level_0__": ["Put cube in dish"]}),
                dataset / "meta" / "tasks.parquet",
            )

            catalog = scan_catalog(root)

            self.assertTrue(catalog[0].valid)
            self.assertEqual(catalog[0].tasks[0].prompt, "Put cube in dish")

    def test_quarantines_dataset_with_only_one_video_camera(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = write_dataset(Path(tmp), "one-camera")
            info_path = dataset / "meta" / "info.json"
            info = json.loads(info_path.read_text())
            del info["features"]["observation.images.top"]
            info_path.write_text(json.dumps(info))
            catalog = scan_catalog(Path(tmp))

            self.assertFalse(catalog[0].valid)
            self.assertIn("fewer than two video cameras", catalog[0].issues)

    def test_quarantines_v3_dataset_when_episode_count_disagrees_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root, "episode-count-mismatch")
            info_path = dataset / "meta" / "info.json"
            info = json.loads(info_path.read_text())
            info["total_episodes"] = 2
            info_path.write_text(json.dumps(info))

            catalog = scan_catalog(root)

            self.assertFalse(catalog[0].valid)
            self.assertIn(
                "episode count does not match metadata: info.json declares 2, "
                "but episode metadata contains 1 row",
                catalog[0].issues,
            )

    def test_quarantines_v21_dataset_when_episode_count_disagrees_with_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "v21-count-mismatch"
            (dataset / "meta").mkdir(parents=True)
            (dataset / "data" / "chunk-000").mkdir(parents=True)
            (dataset / "meta" / "info.json").write_text(
                json.dumps(
                    {
                        "codebase_version": "v2.1",
                        "fps": 30,
                        "total_episodes": 2,
                        "total_frames": 90,
                        "features": {
                            "front": {"dtype": "video"},
                            "top": {"dtype": "video"},
                        },
                    }
                )
            )
            (dataset / "meta" / "tasks.jsonl").write_text(
                '{"task_index": 0, "task": "Fold cloth"}\n'
            )
            (dataset / "meta" / "episodes.jsonl").write_text(
                '{"episode_index": 0, "length": 90, "task_index": 0}\n'
            )
            pq.write_table(
                pa.table({"frame_index": list(range(90))}),
                dataset / "data" / "chunk-000" / "file-000.parquet",
            )

            catalog = scan_catalog(root)

            self.assertFalse(catalog[0].valid)
            self.assertIn(
                "episode count does not match metadata: info.json declares 2, "
                "but episode metadata contains 1 row",
                catalog[0].issues,
            )

    def test_excludes_short_and_structurally_invalid_episodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_dataset(root, "short", duration=1.9)
            write_dataset(root, "broken", valid=False)

            catalog = scan_catalog(root)
            by_name = {dataset.name: dataset for dataset in catalog}

            self.assertEqual(by_name["short"].usable_episodes, 0)
            self.assertEqual(by_name["short"].episodes[0].exclusion_reason, "shorter than 2 seconds")
            self.assertFalse(by_name["broken"].valid)
            self.assertIn("invalid parquet", by_name["broken"].issues[0])


if __name__ == "__main__":
    unittest.main()
