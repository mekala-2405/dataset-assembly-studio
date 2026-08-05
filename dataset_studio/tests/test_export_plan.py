import tempfile
import unittest
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backend.catalog import Dataset, Episode, Task
from backend.export_plan import build_export_plan
from backend.joint_mapping import CANONICAL_JOINTS


def _source(root: Path, name: str, action_size: int = 6) -> Dataset:
    path = root / name
    data = path / "data" / "chunk-000"
    video = path / "videos"
    data.mkdir(parents=True)
    video.mkdir()
    table = pa.table(
        {
            "action": pa.array([[0.0] * action_size] * 90, type=pa.list_(pa.float32(), action_size)),
            "observation.state": pa.array([[0.0] * 6] * 90, type=pa.list_(pa.float32(), 6)),
            "episode_index": pa.array([0] * 90, type=pa.int64()),
        }
    )
    pq.write_table(table, data / "episode_000000.parquet")
    (path / "meta").mkdir()
    (path / "meta/info.json").write_text(
        json.dumps(
            {
                "features": {
                    "action": {"shape": [action_size], "names": list(CANONICAL_JOINTS)[:action_size]},
                    "observation.state": {"shape": [6], "names": list(CANONICAL_JOINTS)},
                }
            }
        )
    )
    wrist = video / "wrist.mp4"
    front = video / "front.mp4"
    wrist.write_bytes(b"video")
    front.write_bytes(b"video")
    return Dataset(
        path=str(path),
        name=name,
        version="v2.1",
        fps=30,
        cameras=["cam_wrist", "cam_front"],
        tasks=[Task(0, "source prompt")],
        episodes=[
            Episode(
                0,
                0,
                3.0,
                video_files={"cam_wrist": str(wrist), "cam_front": str(front)},
                video_starts={"cam_wrist": 0.0, "cam_front": 0.0},
            )
        ],
    )


def _checkpoint(dataset: Dataset, prompt: str, revision: int = 1) -> dict:
    return {
        "status": "approved",
        "revision": revision,
        "updated_by": "alice",
        "recipe": {
            "choices": [
                {
                    "dataset_path": dataset.path,
                    "episode_index": 0,
                    "final_prompt": prompt,
                    "duration_seconds": 3.0,
                }
            ],
            "camera_mapping": {"cam_wrist": "wrist", "cam_front": "front"},
            "joint_mapping": {
                "action": {name: index for index, name in enumerate(CANONICAL_JOINTS)},
                "observation.state": {name: index for index, name in enumerate(CANONICAL_JOINTS)},
            },
        },
    }


class ExportPlanTests(unittest.TestCase):
    def test_uses_only_approved_checkpoints_and_caps_tasks_deterministically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            b = _source(root, "b")
            a = _source(root, "a")
            shared = {
                "checkpoints": {
                    b.path: _checkpoint(b, "Pick"),
                    a.path: _checkpoint(a, "Pick"),
                    "/draft": {"status": "draft", "recipe": {"choices": []}},
                }
            }
            settings = {"second_camera": "front", "max_per_task": 1}

            plan = build_export_plan([b, a], shared, settings, root / "export")

            self.assertFalse(plan.errors)
            self.assertEqual(plan.selected_task_counts, {"Pick": 2})
            self.assertEqual(plan.retained_task_counts, {"Pick": 1})
            self.assertEqual([(e.dataset_path, e.source_episode_index) for e in plan.episodes], [(a.path, 0)])
            self.assertEqual(plan.episodes[0].output_episode_index, 0)
            self.assertEqual(plan.episodes[0].output_task_index, 0)
            self.assertEqual(plan.required_cameras, ["wrist", "front"])

    def test_applies_per_prompt_cap_before_deterministic_task_group_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = _source(root, "a")
            b = _source(root, "b")
            c = _source(root, "c")
            shared = {
                "checkpoints": {
                    a.path: _checkpoint(a, "Place red block in bin"),
                    b.path: _checkpoint(b, "Put blue cube in container"),
                    c.path: _checkpoint(c, "Fold the cloth"),
                }
            }
            policy = {
                "groups": {
                    "container-group": {
                        "name": "Container object placement",
                        "episode_cap": 1,
                        "prompts": [
                            "Place red block in bin",
                            "Put blue cube in container",
                        ],
                    },
                    "fold-group": {
                        "name": "Cloth folding",
                        "episode_cap": None,
                        "prompts": ["Fold the cloth"],
                    },
                }
            }

            plan = build_export_plan(
                [c, b, a],
                shared,
                {"second_camera": "front", "max_per_task": 1},
                root / "export",
                task_group_policy=policy,
            )

            self.assertFalse(plan.errors)
            self.assertEqual(plan.selected_group_counts, {"container-group": 2, "fold-group": 1})
            self.assertEqual(plan.retained_group_counts, {"container-group": 1, "fold-group": 1})
            self.assertEqual(plan.task_group_caps, {"container-group": 1})
            self.assertEqual(
                [(episode.dataset_path, episode.final_prompt) for episode in plan.episodes],
                [(a.path, "Place red block in bin"), (c.path, "Fold the cloth")],
            )

    def test_blocks_duplicates_blank_prompts_missing_camera_short_and_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _source(root, "a")
            source.episodes[0].duration_seconds = 1.0
            first = _checkpoint(source, "")
            second = _checkpoint(source, "")
            first["recipe"]["camera_mapping"] = {"cam_wrist": "wrist"}
            output = root / "export"
            output.mkdir()

            plan = build_export_plan(
                [source],
                {"checkpoints": {source.path: first, f"{source.path}/alias": second}},
                {"second_camera": "front"},
                output,
            )

            messages = "\n".join(error.message for error in plan.errors)
            self.assertIn("duplicate", messages)
            self.assertIn("empty final prompt", messages)
            self.assertIn("shorter than 2 seconds", messages)
            self.assertIn("required camera 'front'", messages)
            self.assertIn("already exists", messages)

    def test_blocks_incompatible_action_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = _source(root, "a", 6)
            b = _source(root, "b", 7)

            plan = build_export_plan(
                [a, b],
                {"checkpoints": {a.path: _checkpoint(a, "A"), b.path: _checkpoint(b, "B")}},
                {"second_camera": "front"},
                root / "export",
            )

            self.assertTrue(any("action schema" in error.message for error in plan.errors))

    def test_accepts_variable_and_fixed_size_float_lists_with_matching_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixed = _source(root, "fixed")
            variable = _source(root, "variable")
            parquet_path = Path(variable.path) / "data/chunk-000/episode_000000.parquet"
            table = pq.read_table(parquet_path)
            table = table.set_column(
                table.schema.get_field_index("action"),
                "action",
                pa.array(table["action"].to_pylist(), type=pa.list_(pa.float32())),
            )
            pq.write_table(table, parquet_path)

            plan = build_export_plan(
                [fixed, variable],
                {
                    "checkpoints": {
                        fixed.path: _checkpoint(fixed, "A"),
                        variable.path: _checkpoint(variable, "B"),
                    }
                },
                {"second_camera": "front"},
                root / "export",
            )

            self.assertFalse(
                any("action schema" in error.message for error in plan.errors),
                [error.message for error in plan.errors],
            )

    def test_accepts_source_joint_aliases_when_frozen_mappings_are_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = _source(root, "a")
            b = _source(root, "b")
            info_path = Path(b.path) / "meta/info.json"
            info = json.loads(info_path.read_text())
            info["features"]["action"]["names"] = [
                "main_shoulder_pan",
                "main_shoulder_lift",
                "main_elbow_flex",
                "main_wrist_flex",
                "main_wrist_roll",
                "main_gripper",
            ]
            info_path.write_text(json.dumps(info))

            plan = build_export_plan(
                [a, b],
                {"checkpoints": {a.path: _checkpoint(a, "A"), b.path: _checkpoint(b, "B")}},
                {"second_camera": "front"},
                root / "export",
            )

            self.assertFalse(
                any("action schema" in error.message for error in plan.errors),
                [error.message for error in plan.errors],
            )

    def test_blocks_empty_approved_checkpoint_instead_of_silently_omitting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _source(root, "a")
            plan = build_export_plan(
                [source],
                {
                    "checkpoints": {
                        source.path: {
                            "status": "approved",
                            "revision": 1,
                            "recipe": {"choices": [], "camera_mapping": {}},
                        }
                    }
                },
                {"second_camera": "front"},
                root / "export",
            )

            self.assertTrue(any("no selected episodes" in error.message for error in plan.errors))

    def test_freezes_complete_joint_mapping_and_blocks_missing_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _source(root, "a")
            approved = _checkpoint(source, "Pick")

            plan = build_export_plan(
                [source], {"checkpoints": {source.path: approved}}, {"second_camera": "front"}, root / "export"
            )
            self.assertEqual(plan.episodes[0].joint_mapping["action"]["gripper.pos"], 5)

            del approved["recipe"]["joint_mapping"]
            blocked = build_export_plan(
                [source], {"checkpoints": {source.path: approved}}, {"second_camera": "front"}, root / "other"
            )
            self.assertTrue(any(error.category == "joints" and error.phase == "joints" for error in blocked.errors))


if __name__ == "__main__":
    unittest.main()
