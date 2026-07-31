import tempfile
import unittest
from pathlib import Path

from backend.workspaces import claim_dataset, load_claims, load_shared_checkpoints, load_workspace, migrate_legacy_workspaces, release_all_claims, release_dataset, save_checkpoint


class WorkspaceTests(unittest.TestCase):
    def test_users_have_independent_editable_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save_checkpoint(root, "alice", "/data/a", "approved", {"episodes": [0]})
            save_checkpoint(root, "bob", "/data/a", "excluded", {"reason": "bad view"})
            save_checkpoint(root, "alice", "/data/a", "draft", {"episodes": [0, 1]})

            self.assertEqual(load_workspace(root, "alice")["checkpoints"]["/data/a"]["status"], "draft")
            self.assertEqual(load_workspace(root, "bob")["checkpoints"]["/data/a"]["status"], "excluded")

    def test_claim_prevents_another_user_from_opening_same_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim_dataset(root, "alice", "/data/a")
            with self.assertRaisesRegex(ValueError, "claimed by alice"):
                claim_dataset(root, "bob", "/data/a")
            release_dataset(root, "alice", "/data/a")
            claim_dataset(root, "bob", "/data/a")
            self.assertEqual(load_claims(root)["claims"]["/data/a"], "bob")

    def test_shared_checkpoint_survives_release_and_is_inherited(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim_dataset(root, "alice", "/data/a")
            save_checkpoint(root, "alice", "/data/a", "draft", {"episodes": [1, 2]})
            release_all_claims(root, "alice")
            claim_dataset(root, "bob", "/data/a")

            shared = load_shared_checkpoints(root)["checkpoints"]["/data/a"]
            self.assertEqual(shared["recipe"], {"episodes": [1, 2]})
            self.assertEqual(shared["updated_by"], "alice")
            self.assertEqual(shared["revision"], 1)

    def test_migrates_legacy_local_checkpoint_without_overwriting_shared_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / ".dataset_studio/workspaces/alice.json"
            workspace.parent.mkdir(parents=True)
            workspace.write_text(
                '{"user":"alice","checkpoints":{"/data/a":{"status":"approved","recipe":{"choices":[1]}}}}'
            )

            self.assertEqual(migrate_legacy_workspaces(root), 1)
            self.assertEqual(migrate_legacy_workspaces(root), 0)
            shared = load_shared_checkpoints(root)
            self.assertEqual(shared["checkpoints"]["/data/a"]["status"], "approved")
            self.assertEqual(shared["history"]["/data/a"][0]["updated_by"], "alice")


if __name__ == "__main__":
    unittest.main()
