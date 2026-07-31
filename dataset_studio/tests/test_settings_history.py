import tempfile
import unittest
from pathlib import Path

from backend.settings import load_settings, save_settings
from backend.workspaces import checkpoint_history, save_checkpoint


class SettingsHistoryTests(unittest.TestCase):
    def test_settings_are_persisted_with_fixed_export_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = save_settings(
                root,
                {
                    "output_name": "combined_so101",
                    "output_parent": str(root / "exports"),
                    "second_camera": "front",
                    "max_per_task": 12,
                },
            )

            self.assertEqual(load_settings(root), saved)
            self.assertEqual(saved["required_cameras"], ["wrist", "front"])
            self.assertEqual(saved["fps"], 30)
            self.assertEqual(saved["width"], 640)
            self.assertEqual(saved["height"], 480)
            self.assertEqual(saved["codec"], "h264")

    def test_checkpoint_history_is_append_only_and_deep_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipe = {"choices": [{"episode_index": 1}], "reason": "first"}
            save_checkpoint(root, "alice", "/data/a", "draft", recipe)
            recipe["choices"][0]["episode_index"] = 99
            save_checkpoint(root, "alice", "/data/a", "approved", {"choices": [{"episode_index": 2}]})

            history = checkpoint_history(root, "/data/a")
            self.assertEqual([item["revision"] for item in history], [1, 2])
            self.assertEqual(history[0]["recipe"]["choices"][0]["episode_index"], 1)
            self.assertEqual(history[1]["status"], "approved")
            self.assertEqual(history[1]["updated_by"], "alice")
            self.assertIn("updated_at", history[0])

    def test_excluded_checkpoint_requires_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "reason"):
                save_checkpoint(Path(tmp), "alice", "/data/a", "excluded", {})


if __name__ == "__main__":
    unittest.main()
