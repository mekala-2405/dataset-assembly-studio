import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.named_workspaces import create_named_workspace, ensure_workspace_registry, switch_named_workspace
from backend.workspaces import load_claims, load_shared_checkpoints


class NamedWorkspaceTests(unittest.TestCase):
    def make_active_state(self, root: Path) -> dict[str, str]:
        studio = root / ".dataset_studio"
        (studio / "workspaces").mkdir(parents=True)
        claims = '{"claims":{"/datasets/current":"alice"}}\n'
        checkpoints = (
            '{"checkpoints":{"/datasets/current":{"status":"approved"}},'
            '"history":{"/datasets/current":[{"status":"approved"}]}}\n'
        )
        workspace = '{"user":"alice","checkpoints":{"/datasets/current":{"status":"approved"}}}\n'
        settings = '{"output_name":"preserve-me"}\n'
        job = '{"id":"job-1","status":"completed"}\n'
        archive = b"prepared archive bytes\\x00\\xff"
        (studio / "claims.json").write_text(claims)
        (studio / "dataset_checkpoints.json").write_text(checkpoints)
        (studio / "workspaces" / "alice.json").write_text(workspace)
        (studio / "settings.json").write_text(settings)
        (studio / "jobs").mkdir()
        (studio / "jobs" / "job-1.json").write_text(job)
        (studio / "downloads").mkdir()
        (studio / "downloads" / "job-1.tar.gz").write_bytes(archive)
        return {
            "claims": claims,
            "checkpoints": checkpoints,
            "workspace": workspace,
            "settings": settings,
            "job": job,
            "archive": archive,
        }

    def test_registering_and_creating_workspace_snapshots_active_state_only(self):
        """Would fail if registration modifies state or creation omits an active target."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = self.make_active_state(root)

            registry = ensure_workspace_registry(root)
            self.assertEqual(len(registry["workspaces"]), 1)
            self.assertEqual((root / ".dataset_studio" / "claims.json").read_text(), original["claims"])

            created = create_named_workspace(
                root,
                current_name="Development tests",
                new_name="Production curation",
                confirmation="START NEW WORKSPACE",
            )

            self.assertEqual(created["active_workspace"]["name"], "Production curation")
            self.assertEqual(load_claims(root), {"claims": {}})
            self.assertEqual(load_shared_checkpoints(root), {"checkpoints": {}, "history": {}})
            snapshot = root / ".dataset_studio" / "saved_workspaces" / created["previous_workspace"]["id"]
            self.assertTrue((snapshot / "claims.json").is_file())
            self.assertEqual((snapshot / "dataset_checkpoints.json").read_text(), original["checkpoints"])
            self.assertEqual((snapshot / "workspaces" / "alice.json").read_text(), original["workspace"])
            self.assertEqual((root / ".dataset_studio" / "settings.json").read_text(), original["settings"])
            self.assertEqual((root / ".dataset_studio" / "jobs" / "job-1.json").read_text(), original["job"])
            self.assertEqual((root / ".dataset_studio" / "downloads" / "job-1.tar.gz").read_bytes(), original["archive"])

    def test_create_validates_confirmation_and_workspace_names(self):
        """Would fail if unsafe, duplicate, or unconfirmed requests could change workspace state."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            registry = ensure_workspace_registry(root)

            with self.assertRaisesRegex(ValueError, "START NEW WORKSPACE"):
                create_named_workspace(root, "Development tests", "Production curation", "start")
            with self.assertRaisesRegex(ValueError, "blank"):
                create_named_workspace(root, "Development tests", " ", "START NEW WORKSPACE")
            with self.assertRaisesRegex(ValueError, "slash"):
                create_named_workspace(root, "Development tests", "bad/name", "START NEW WORKSPACE")
            with self.assertRaisesRegex(ValueError, "blank"):
                create_named_workspace(root, " ", "Production curation", "START NEW WORKSPACE")

            created = create_named_workspace(root, "Development tests", "Production curation", "START NEW WORKSPACE")
            with self.assertRaisesRegex(ValueError, "already exists"):
                create_named_workspace(root, "Production curation", "production curation", "START NEW WORKSPACE")
            with self.assertRaisesRegex(ValueError, "already exists"):
                create_named_workspace(root, "development tests", "Research curation", "START NEW WORKSPACE")
            with self.assertRaisesRegex(ValueError, "SWITCH WORKSPACE"):
                switch_named_workspace(root, registry["active_workspace_id"], "switch")
            with self.assertRaisesRegex(ValueError, "does not exist"):
                switch_named_workspace(root, "missing", "SWITCH WORKSPACE")
            self.assertEqual(created["active_workspace"]["name"], "Production curation")

    def test_switch_restores_each_workspace_active_state_in_both_directions(self):
        """Would fail if switching lost claims, checkpoint history, or per-user workspace files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = self.make_active_state(root)
            ensure_workspace_registry(root)
            created = create_named_workspace(root, "Development tests", "Production curation", "START NEW WORKSPACE")

            studio = root / ".dataset_studio"
            production_claims = {"claims": {"/datasets/production": "bob"}}
            production_checkpoints = {
                "checkpoints": {"/datasets/production": {"status": "excluded", "reason": "duplicate"}},
                "history": {"/datasets/production": [{"status": "excluded", "reason": "duplicate"}]},
            }
            (studio / "claims.json").write_text(json.dumps(production_claims))
            (studio / "dataset_checkpoints.json").write_text(json.dumps(production_checkpoints))
            (studio / "workspaces" / "bob.json").write_text('{"user":"bob","checkpoints":{"/datasets/production":{}}}')

            switched_old = switch_named_workspace(
                root,
                created["previous_workspace"]["id"],
                "SWITCH WORKSPACE",
            )
            self.assertEqual(switched_old["active_workspace"]["name"], "Development tests")
            self.assertEqual((studio / "claims.json").read_text(), original["claims"])
            self.assertEqual((studio / "dataset_checkpoints.json").read_text(), original["checkpoints"])
            self.assertEqual((studio / "workspaces" / "alice.json").read_text(), original["workspace"])
            self.assertFalse((studio / "workspaces" / "bob.json").exists())

            switched_new = switch_named_workspace(
                root,
                created["active_workspace"]["id"],
                "SWITCH WORKSPACE",
            )
            self.assertEqual(switched_new["active_workspace"]["name"], "Production curation")
            self.assertEqual(load_claims(root), production_claims)
            self.assertEqual(load_shared_checkpoints(root), production_checkpoints)
            self.assertTrue((studio / "workspaces" / "bob.json").is_file())
            names = [workspace["name"] for workspace in ensure_workspace_registry(root)["workspaces"]]
            self.assertEqual(names, ["Development tests", "Production curation"])

    def test_failed_snapshot_copy_leaves_registry_and_active_state_unchanged(self):
        """Would fail if a disk-full snapshot error partially renamed state or the registry."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            registry_before = json.loads((studio / "workspace_registry.json").read_text())
            active_before = {
                "claims": (studio / "claims.json").read_bytes(),
                "checkpoints": (studio / "dataset_checkpoints.json").read_bytes(),
                "workspace": (studio / "workspaces" / "alice.json").read_bytes(),
            }

            with patch("shutil.copytree", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    create_named_workspace(root, "Development tests", "Production curation", "START NEW WORKSPACE")

            self.assertEqual(json.loads((studio / "workspace_registry.json").read_text()), registry_before)
            self.assertEqual((studio / "claims.json").read_bytes(), active_before["claims"])
            self.assertEqual((studio / "dataset_checkpoints.json").read_bytes(), active_before["checkpoints"])
            self.assertEqual((studio / "workspaces" / "alice.json").read_bytes(), active_before["workspace"])
            self.assertEqual((studio / "settings.json").read_text(), original["settings"])


if __name__ == "__main__":
    unittest.main()
