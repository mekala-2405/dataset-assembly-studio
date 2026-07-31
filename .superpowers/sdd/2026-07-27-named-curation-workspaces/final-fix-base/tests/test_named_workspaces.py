import json
import os
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
        manifest = '{"job_id":"job-1","episodes":[0]}\n'
        archive = b"prepared archive bytes\\x00\\xff"
        (studio / "claims.json").write_text(claims)
        (studio / "dataset_checkpoints.json").write_text(checkpoints)
        (studio / "workspaces" / "alice.json").write_text(workspace)
        (studio / "settings.json").write_text(settings)
        (studio / "jobs").mkdir()
        (studio / "jobs" / "job-1.json").write_text(job)
        (studio / "jobs" / "job-1.manifest.json").write_text(manifest)
        (studio / "downloads").mkdir()
        (studio / "downloads" / "job-1.tar.gz").write_bytes(archive)
        (root / "source_dataset" / "meta").mkdir(parents=True)
        (root / "source_dataset" / "meta" / "info.json").write_text('{"source":"preserve-me"}\n')
        (root / "exports" / ".staging-job-1").mkdir(parents=True)
        (root / "exports" / ".staging-job-1" / "partial.txt").write_text("staging preserve-me\n")
        (root / "exports" / "completed" / "meta").mkdir(parents=True)
        (root / "exports" / "completed" / "meta" / "info.json").write_text('{"completed":"preserve-me"}\n')
        return {
            "claims": claims,
            "checkpoints": checkpoints,
            "workspace": workspace,
            "settings": settings,
            "job": job,
            "manifest": manifest,
            "archive": archive,
            "source": '{"source":"preserve-me"}\n',
            "staging": "staging preserve-me\n",
            "completed": '{"completed":"preserve-me"}\n',
        }

    def active_state_bytes(self, studio: Path) -> dict:
        return {
            "claims": (studio / "claims.json").read_bytes(),
            "checkpoints": (studio / "dataset_checkpoints.json").read_bytes(),
            "workspaces": {
                path.relative_to(studio / "workspaces").as_posix(): path.read_bytes()
                for path in sorted((studio / "workspaces").rglob("*"))
                if path.is_file()
            },
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
            self.assertEqual((root / ".dataset_studio" / "jobs" / "job-1.manifest.json").read_text(), original["manifest"])
            self.assertEqual((root / ".dataset_studio" / "downloads" / "job-1.tar.gz").read_bytes(), original["archive"])
            self.assertEqual((root / "source_dataset" / "meta" / "info.json").read_text(), original["source"])
            self.assertEqual((root / "exports" / ".staging-job-1" / "partial.txt").read_text(), original["staging"])
            self.assertEqual((root / "exports" / "completed" / "meta" / "info.json").read_text(), original["completed"])

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

    def test_failed_activation_and_transient_rollback_restore_preserve_active_state(self):
        """Would fail if a failed restore discarded rollback data or left an active target missing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            created = create_named_workspace(root, "Development tests", "Production curation", "START NEW WORKSPACE")
            studio = root / ".dataset_studio"
            (studio / "claims.json").write_text('{"claims":{"/datasets/production":"bob"}}\n')
            (studio / "dataset_checkpoints.json").write_text('{"checkpoints":{},"history":{}}\n')
            (studio / "workspaces" / "bob.json").write_text('{"user":"bob","checkpoints":{}}\n')
            active_before = self.active_state_bytes(studio)
            registry_before = (studio / "workspace_registry.json").read_bytes()
            real_replace = os.replace
            injected = {"install": False, "rollback": False}

            def fail_install_and_one_restore(source, destination):
                source = Path(source)
                destination = Path(destination)
                if (
                    not injected["install"]
                    and source.parent.name.startswith(".restore-")
                    and destination == studio / "dataset_checkpoints.json"
                ):
                    injected["install"] = True
                    raise OSError("target move failed")
                if (
                    injected["install"]
                    and not injected["rollback"]
                    and source.parent.name.startswith(".rollback-")
                    and destination == studio / "claims.json"
                ):
                    injected["rollback"] = True
                    raise OSError("rollback move failed")
                return real_replace(source, destination)

            with patch("backend.named_workspaces.os.replace", side_effect=fail_install_and_one_restore):
                with self.assertRaisesRegex(OSError, "target move failed"):
                    switch_named_workspace(root, created["previous_workspace"]["id"], "SWITCH WORKSPACE")

            self.assertTrue(injected["install"])
            self.assertTrue(injected["rollback"])
            self.assertEqual(self.active_state_bytes(studio), active_before)
            self.assertEqual((studio / "workspace_registry.json").read_bytes(), registry_before)

    def test_registry_atomic_replace_failure_restores_prior_active_state(self):
        """Would fail if a registry persistence error stranded newly activated state."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            active_before = self.active_state_bytes(studio)
            registry_before = (studio / "workspace_registry.json").read_bytes()
            real_replace = os.replace

            def fail_registry_replace(source, destination):
                if Path(destination) == studio / "workspace_registry.json":
                    raise OSError("registry disk full")
                return real_replace(source, destination)

            with patch("backend.named_workspaces.os.replace", side_effect=fail_registry_replace):
                with self.assertRaisesRegex(OSError, "registry disk full"):
                    create_named_workspace(root, "Development tests", "Production curation", "START NEW WORKSPACE")

            self.assertEqual(self.active_state_bytes(studio), active_before)
            self.assertEqual((studio / "workspace_registry.json").read_bytes(), registry_before)

    def test_permanent_rollback_move_failure_keeps_recovery_copy_and_active_state(self):
        """Would fail if an unrecoverable rollback move deleted the only usable recovery copy."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            created = create_named_workspace(root, "Development tests", "Production curation", "START NEW WORKSPACE")
            studio = root / ".dataset_studio"
            (studio / "claims.json").write_text('{"claims":{"/datasets/production":"bob"}}\n')
            (studio / "dataset_checkpoints.json").write_text('{"checkpoints":{},"history":{}}\n')
            (studio / "workspaces" / "bob.json").write_text('{"user":"bob","checkpoints":{}}\n')
            active_before = self.active_state_bytes(studio)
            real_replace = os.replace

            def fail_install_and_all_claim_restores(source, destination):
                source = Path(source)
                destination = Path(destination)
                if source.parent.name.startswith(".restore-") and destination == studio / "dataset_checkpoints.json":
                    raise OSError("target move failed")
                if source.parent.name.startswith(".rollback-") and destination == studio / "claims.json":
                    raise OSError("rollback move failed")
                return real_replace(source, destination)

            with patch("backend.named_workspaces.os.replace", side_effect=fail_install_and_all_claim_restores):
                with self.assertRaisesRegex(OSError, "target move failed"):
                    switch_named_workspace(root, created["previous_workspace"]["id"], "SWITCH WORKSPACE")

            self.assertEqual(self.active_state_bytes(studio), active_before)
            recovery = list(studio.glob(".rollback-*"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual((recovery[0] / "claims.json").read_bytes(), active_before["claims"])


if __name__ == "__main__":
    unittest.main()
