import json
import os
import shutil
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backend import named_workspaces as named_workspaces_module
from backend import workspaces as workspaces_module
from backend.named_workspaces import create_named_workspace, ensure_workspace_registry, switch_named_workspace
from backend.workspaces import load_claims, load_shared_checkpoints, save_checkpoint


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

    def test_failed_transition_marker_cleanup_retains_restore_and_rollback_paths(self):
        """Would fail if rollback cleanup removed recovery paths before durable marker removal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"

            with (
                patch("backend.named_workspaces._write_registry", side_effect=OSError("registry denied")),
                patch("backend.named_workspaces._remove_transition_marker", side_effect=OSError("marker denied")),
            ):
                with self.assertRaisesRegex(OSError, "registry denied"):
                    create_named_workspace(
                        root,
                        current_name="Development tests",
                        new_name="Production curation",
                        confirmation="START NEW WORKSPACE",
                    )

            marker = json.loads((studio / "workspace_transition.json").read_text())
            self.assertEqual(marker["phase"], "registry_pending")
            self.assertTrue(Path(marker["restore_path"]).is_dir())
            self.assertTrue(Path(marker["rollback_path"]).is_dir())

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

    def test_create_cleanup_failure_after_commit_returns_success_and_recovery_path(self):
        """Would fail if rollback cleanup could turn a committed create into an API failure."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            initial = ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            real_rmtree = shutil.rmtree

            def fail_rollback_cleanup(path, *args, **kwargs):
                if Path(path).name.startswith(".rollback-"):
                    raise OSError("cleanup denied")
                return real_rmtree(path, *args, **kwargs)

            with patch("backend.named_workspaces.shutil.rmtree", side_effect=fail_rollback_cleanup):
                created = create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )

            registry = json.loads((studio / "workspace_registry.json").read_text())
            self.assertEqual(registry["active_workspace_id"], created["active_workspace"]["id"])
            self.assertNotEqual(registry["active_workspace_id"], initial["active_workspace_id"])
            self.assertEqual(json.loads((studio / "claims.json").read_text()), {"claims": {}})
            self.assertEqual(
                json.loads((studio / "dataset_checkpoints.json").read_text()),
                {"checkpoints": {}, "history": {}},
            )
            recovery = list(studio.glob(".rollback-*"))
            self.assertEqual(len(recovery), 1)
            self.assertTrue(any(str(recovery[0]) in warning for warning in created["cleanup_warnings"]))

    def test_switch_cleanup_failure_after_commit_returns_success_and_consistent_registry(self):
        """Would fail if cleanup could report a failed switch after active state and registry changed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = self.make_active_state(root)
            ensure_workspace_registry(root)
            created = create_named_workspace(
                root,
                current_name="Development tests",
                new_name="Production curation",
                confirmation="START NEW WORKSPACE",
            )
            studio = root / ".dataset_studio"
            (studio / "claims.json").write_text('{"claims":{"/datasets/production":"bob"}}\n')
            real_rmtree = shutil.rmtree

            def fail_rollback_cleanup(path, *args, **kwargs):
                if Path(path).name.startswith(".rollback-"):
                    raise OSError("cleanup denied")
                return real_rmtree(path, *args, **kwargs)

            with patch("backend.named_workspaces.shutil.rmtree", side_effect=fail_rollback_cleanup):
                switched = switch_named_workspace(
                    root,
                    created["previous_workspace"]["id"],
                    "SWITCH WORKSPACE",
                )

            registry = json.loads((studio / "workspace_registry.json").read_text())
            self.assertEqual(registry["active_workspace_id"], switched["active_workspace"]["id"])
            self.assertEqual(registry["active_workspace_id"], created["previous_workspace"]["id"])
            self.assertEqual((studio / "claims.json").read_text(), original["claims"])
            recovery = list(studio.glob(".rollback-*"))
            self.assertEqual(len(recovery), 1)
            self.assertTrue(any(str(recovery[0]) in warning for warning in switched["cleanup_warnings"]))

    def test_post_commit_marker_unlink_failure_retains_named_recovery_paths(self):
        """Would fail if marker cleanup discarded recovery paths after the registry committed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"

            with patch(
                "backend.named_workspaces._remove_transition_marker",
                side_effect=OSError("marker unlink denied"),
            ):
                created = create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )

            marker_path = studio / "workspace_transition.json"
            marker = json.loads(marker_path.read_text())
            restore = Path(marker["restore_path"])
            rollback = Path(marker["rollback_path"])
            self.assertEqual(marker["phase"], "committed")
            self.assertTrue(restore.is_dir())
            self.assertTrue(rollback.is_dir())
            self.assertTrue(any(str(marker_path) in warning for warning in created["cleanup_warnings"]))
            self.assertTrue(any(str(restore) in warning for warning in created["cleanup_warnings"]))
            self.assertTrue(any(str(rollback) in warning for warning in created["cleanup_warnings"]))

    def test_post_commit_marker_directory_fsync_failure_recreates_marker_and_retains_recovery_paths(self):
        """Would fail if an uncertain marker unlink removed the artifacts needed for safe recovery."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            marker_path = studio / "workspace_transition.json"
            real_fsync_directory = named_workspaces_module._fsync_directory
            real_remove_marker = named_workspaces_module._remove_transition_marker
            failed = {"value": False}
            removing = {"value": False}

            def fail_first_marker_removal_fsync(path):
                if Path(path) == studio and removing["value"] and not failed["value"]:
                    failed["value"] = True
                    raise OSError("marker directory fsync denied")
                return real_fsync_directory(path)

            def observe_marker_removal(root_arg):
                removing["value"] = True
                try:
                    return real_remove_marker(root_arg)
                finally:
                    removing["value"] = False

            with (
                patch("backend.named_workspaces._fsync_directory", side_effect=fail_first_marker_removal_fsync),
                patch("backend.named_workspaces._remove_transition_marker", side_effect=observe_marker_removal),
            ):
                created = create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )

            self.assertTrue(failed["value"])
            marker = json.loads(marker_path.read_text())
            restore = Path(marker["restore_path"])
            rollback = Path(marker["rollback_path"])
            self.assertEqual(marker["phase"], "committed")
            self.assertTrue(restore.is_dir())
            self.assertTrue(rollback.is_dir())
            self.assertTrue(any("fsync denied" in warning for warning in created["cleanup_warnings"]))
            self.assertTrue(any(str(restore) in warning for warning in created["cleanup_warnings"]))
            self.assertTrue(any(str(rollback) in warning for warning in created["cleanup_warnings"]))

    def test_post_commit_marker_update_and_unlink_failure_rewrites_committed_phase(self):
        """Would fail if a successful registry commit retained a stale registry_pending marker."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            real_update = named_workspaces_module._update_transition_marker

            def fail_committed_update(root_arg, **changes):
                if changes.get("phase") == "committed":
                    raise OSError("committed marker update denied")
                return real_update(root_arg, **changes)

            with (
                patch("backend.named_workspaces._update_transition_marker", side_effect=fail_committed_update),
                patch("backend.named_workspaces._remove_transition_marker", side_effect=OSError("marker unlink denied")),
            ):
                created = create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )

            marker = json.loads((studio / "workspace_transition.json").read_text())
            self.assertEqual(marker["phase"], "committed")
            self.assertTrue(Path(marker["restore_path"]).is_dir())
            self.assertTrue(Path(marker["rollback_path"]).is_dir())
            self.assertTrue(any("committed marker update denied" in warning for warning in created["cleanup_warnings"]))

    def test_save_started_before_create_finishes_in_the_previous_workspace_snapshot(self):
        """Would fail if a transition could move active files out from under a successful save."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            save_at_file_write = threading.Barrier(2, timeout=2)
            release_save = threading.Event()
            snapshot_entered = threading.Event()
            real_locked_json = workspaces_module._locked_json
            real_snapshot = named_workspaces_module._snapshot_workspace
            blocked = {"shared": False}
            errors: list[Exception] = []
            created: dict = {}

            @contextmanager
            def block_first_shared_write(path, default):
                with real_locked_json(path, default) as payload:
                    if Path(path).name == "dataset_checkpoints.json" and not blocked["shared"]:
                        blocked["shared"] = True
                        save_at_file_write.wait()
                        if not release_save.wait(2):
                            raise AssertionError("save release timed out")
                    yield payload

            def observe_snapshot(*args, **kwargs):
                snapshot_entered.set()
                return real_snapshot(*args, **kwargs)

            def save():
                try:
                    save_checkpoint(root, "alice", "/datasets/barrier", "draft", {"episodes": [7]})
                except Exception as error:
                    errors.append(error)

            def create():
                try:
                    created.update(create_named_workspace(
                        root,
                        current_name="Development tests",
                        new_name="Production curation",
                        confirmation="START NEW WORKSPACE",
                    ))
                except Exception as error:
                    errors.append(error)

            with (
                patch("backend.workspaces._locked_json", side_effect=block_first_shared_write),
                patch("backend.named_workspaces._snapshot_workspace", side_effect=observe_snapshot),
            ):
                save_thread = threading.Thread(target=save, daemon=True)
                save_thread.start()
                save_at_file_write.wait()
                create_thread = threading.Thread(target=create, daemon=True)
                create_thread.start()
                reached_snapshot_before_save_finished = snapshot_entered.wait(0.2)
                release_save.set()
                save_thread.join(2)
                create_thread.join(2)

            self.assertFalse(save_thread.is_alive() or create_thread.is_alive())
            self.assertFalse(errors)
            self.assertFalse(
                reached_snapshot_before_save_finished,
                "exclusive transition entered snapshot while the save still held its operation",
            )
            previous_id = created["previous_workspace"]["id"]
            snapshot = json.loads(
                (studio / "saved_workspaces" / previous_id / "dataset_checkpoints.json").read_text()
            )
            self.assertEqual(snapshot["checkpoints"]["/datasets/barrier"]["recipe"], {"episodes": [7]})
            self.assertNotIn("/datasets/barrier", json.loads((studio / "dataset_checkpoints.json").read_text())["checkpoints"])

    def test_save_started_during_create_waits_and_writes_only_to_the_new_workspace(self):
        """Would fail if a save could cross an exclusive transition into the wrong snapshot."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            transition_at_snapshot = threading.Barrier(2, timeout=2)
            release_transition = threading.Event()
            save_started = threading.Barrier(2, timeout=2)
            save_finished = threading.Event()
            real_snapshot = named_workspaces_module._snapshot_workspace
            errors: list[Exception] = []
            created: dict = {}

            def block_snapshot(*args, **kwargs):
                transition_at_snapshot.wait()
                if not release_transition.wait(2):
                    raise AssertionError("transition release timed out")
                return real_snapshot(*args, **kwargs)

            def create():
                try:
                    created.update(create_named_workspace(
                        root,
                        current_name="Development tests",
                        new_name="Production curation",
                        confirmation="START NEW WORKSPACE",
                    ))
                except Exception as error:
                    errors.append(error)

            def save():
                try:
                    save_started.wait()
                    save_checkpoint(root, "bob", "/datasets/barrier", "draft", {"episodes": [9]})
                except Exception as error:
                    errors.append(error)
                finally:
                    save_finished.set()

            with patch("backend.named_workspaces._snapshot_workspace", side_effect=block_snapshot):
                create_thread = threading.Thread(target=create, daemon=True)
                create_thread.start()
                transition_at_snapshot.wait()
                save_thread = threading.Thread(target=save, daemon=True)
                save_thread.start()
                save_started.wait()
                save_completed_before_transition = save_finished.wait(0.2)
                release_transition.set()
                create_thread.join(2)
                save_thread.join(2)

            self.assertFalse(save_thread.is_alive() or create_thread.is_alive())
            self.assertFalse(errors)
            self.assertFalse(
                save_completed_before_transition,
                "shared save completed while the exclusive transition was paused",
            )
            active = json.loads((studio / "dataset_checkpoints.json").read_text())
            self.assertEqual(active["checkpoints"]["/datasets/barrier"]["recipe"], {"episodes": [9]})
            previous_id = created["previous_workspace"]["id"]
            previous = json.loads(
                (studio / "saved_workspaces" / previous_id / "dataset_checkpoints.json").read_text()
            )
            self.assertNotIn("/datasets/barrier", previous["checkpoints"])

    def test_switch_rejects_misidentified_and_malformed_snapshot_targets(self):
        """Would fail if syntactically valid but structurally unsafe snapshots were activated."""
        for corruption in ("wrong-id", "claims-directory", "checkpoint-list", "workspaces-file", "user-list"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.make_active_state(root)
                ensure_workspace_registry(root)
                created = create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )
                studio = root / ".dataset_studio"
                snapshot = studio / "saved_workspaces" / created["previous_workspace"]["id"]
                if corruption == "wrong-id":
                    metadata = json.loads((snapshot / "workspace.json").read_text())
                    metadata["id"] = "different-workspace-id"
                    (snapshot / "workspace.json").write_text(json.dumps(metadata))
                elif corruption == "claims-directory":
                    (snapshot / "claims.json").unlink()
                    (snapshot / "claims.json").mkdir()
                elif corruption == "checkpoint-list":
                    (snapshot / "dataset_checkpoints.json").write_text("[]")
                elif corruption == "workspaces-file":
                    shutil.rmtree(snapshot / "workspaces")
                    (snapshot / "workspaces").write_text("{}")
                else:
                    (snapshot / "workspaces" / "alice.json").write_text("[]")
                registry_before = (studio / "workspace_registry.json").read_bytes()
                active_before = self.active_state_bytes(studio)

                with self.assertRaises(Exception) as caught:
                    switch_named_workspace(
                        root,
                        created["previous_workspace"]["id"],
                        "SWITCH WORKSPACE",
                    )

                self.assertEqual(type(caught.exception).__name__, "WorkspaceSnapshotIntegrityError")
                self.assertEqual((studio / "workspace_registry.json").read_bytes(), registry_before)
                self.assertEqual(self.active_state_bytes(studio), active_before)

    def test_switch_canonicalizes_absent_legacy_snapshot_targets(self):
        """Would fail if an old sparse snapshot activated missing files or directories."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            created = create_named_workspace(
                root,
                current_name="Development tests",
                new_name="Production curation",
                confirmation="START NEW WORKSPACE",
            )
            studio = root / ".dataset_studio"
            snapshot = studio / "saved_workspaces" / created["previous_workspace"]["id"]
            (snapshot / "claims.json").unlink()
            (snapshot / "dataset_checkpoints.json").unlink()
            shutil.rmtree(snapshot / "workspaces")

            switch_named_workspace(
                root,
                created["previous_workspace"]["id"],
                "SWITCH WORKSPACE",
            )

            self.assertEqual(json.loads((studio / "claims.json").read_text()), {"claims": {}})
            self.assertEqual(
                json.loads((studio / "dataset_checkpoints.json").read_text()),
                {"checkpoints": {}, "history": {}},
            )
            self.assertTrue((studio / "workspaces").is_dir())
            self.assertEqual(list((studio / "workspaces").iterdir()), [])

    def test_transition_marker_is_present_before_activation_and_removed_after_commit(self):
        """Would fail if a process interruption could leave mixed state without a durable marker."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            initial = ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            real_activate = named_workspaces_module._activate_restore
            observed: dict = {}

            def inspect_marker(root_arg, restore):
                marker = studio / "workspace_transition.json"
                self.assertTrue(marker.is_file())
                observed.update(json.loads(marker.read_text()))
                return real_activate(root_arg, restore)

            with patch("backend.named_workspaces._activate_restore", side_effect=inspect_marker):
                created = create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )

            self.assertEqual(observed["operation"], "create")
            self.assertEqual(observed["previous_workspace_id"], initial["active_workspace_id"])
            self.assertEqual(observed["target_workspace_id"], created["active_workspace"]["id"])
            self.assertTrue(Path(observed["restore_path"]).name.startswith(".restore-"))
            self.assertFalse((studio / "workspace_transition.json").exists())

    def test_existing_transition_marker_refuses_workspace_use_with_recovery_paths(self):
        """Would fail if startup silently served potentially mixed workspace state."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            studio = root / ".dataset_studio"
            studio.mkdir(parents=True)
            marker = studio / "workspace_transition.json"
            marker.write_text(json.dumps({
                "operation": "switch",
                "phase": "activating",
                "previous_workspace_id": "old-id",
                "target_workspace_id": "new-id",
                "restore_path": str(studio / ".restore-interrupted"),
                "rollback_path": str(studio / ".rollback-interrupted"),
            }))

            with self.assertRaises(Exception) as caught:
                ensure_workspace_registry(root)

            self.assertEqual(type(caught.exception).__name__, "WorkspaceRecoveryRequiredError")
            message = str(caught.exception)
            self.assertIn(str(marker), message)
            self.assertIn(str(studio / ".restore-interrupted"), message)
            self.assertIn(str(studio / ".rollback-interrupted"), message)
            self.assertIn("saved_workspaces/.recovery-*", message)
            self.assertIn("stop the app", message.lower())
            self.assertFalse((studio / "workspace_registry.json").exists())

    def test_registry_rejects_malformed_duplicate_and_traversal_ids_before_path_use(self):
        """Would fail if corrupt persisted registry entries could escape saved_workspaces."""
        valid_workspace = {
            "id": "a" * 32,
            "name": "Development tests",
            "created_at": "2026-07-27T00:00:00+00:00",
            "updated_at": "2026-07-27T00:00:00+00:00",
        }
        corruptions = (
            [],
            {"active_workspace_id": valid_workspace["id"], "workspaces": "not-a-list"},
            {"active_workspace_id": "b" * 32, "workspaces": [valid_workspace]},
            {
                "active_workspace_id": valid_workspace["id"],
                "workspaces": [valid_workspace, {**valid_workspace}],
            },
            {
                "active_workspace_id": "../../outside",
                "workspaces": [{**valid_workspace, "id": "../../outside"}],
            },
        )
        for registry in corruptions:
            with self.subTest(registry=registry), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                studio = root / ".dataset_studio"
                studio.mkdir()
                (studio / "workspace_registry.json").write_text(json.dumps(registry))

                with self.assertRaises(Exception) as caught:
                    ensure_workspace_registry(root)

                self.assertEqual(type(caught.exception).__name__, "WorkspaceSnapshotIntegrityError")
                self.assertIn("registry", str(caught.exception).lower())
                self.assertFalse((root / "outside").exists())

    def test_studio_and_active_target_symlinks_are_rejected_without_external_mutation(self):
        """Would fail if workspace coordination or snapshots followed state outside the dataset root."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "dataset"
            root.mkdir()
            outside_studio = base / "outside-studio"
            outside_studio.mkdir()
            (root / ".dataset_studio").symlink_to(outside_studio, target_is_directory=True)

            with self.assertRaises(Exception) as caught:
                ensure_workspace_registry(root)

            self.assertEqual(type(caught.exception).__name__, "WorkspaceSnapshotIntegrityError")
            self.assertEqual(list(outside_studio.iterdir()), [])

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "dataset"
            external_claims = base / "external-claims.json"
            external_claims.write_text('{"claims":{"external":"owner"}}\n')
            self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            registry_before = (studio / "workspace_registry.json").read_bytes()
            (studio / "claims.json").unlink()
            (studio / "claims.json").symlink_to(external_claims)

            with self.assertRaises(Exception) as caught:
                create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )

            self.assertEqual(type(caught.exception).__name__, "WorkspaceSnapshotIntegrityError")
            self.assertEqual(external_claims.read_text(), '{"claims":{"external":"owner"}}\n')
            self.assertEqual((studio / "workspace_registry.json").read_bytes(), registry_before)
            self.assertFalse((studio / "saved_workspaces").exists())

    def test_snapshot_and_activation_are_fsynced_before_registry_commit(self):
        """Would fail if a successful transition could outlive unsynced staged or renamed state."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_active_state(root)
            ensure_workspace_registry(root)
            studio = root / ".dataset_studio"
            synced_trees: list[Path] = []
            synced_directories: list[Path] = []
            real_fsync_tree = named_workspaces_module._fsync_tree
            real_fsync_directory = named_workspaces_module._fsync_directory
            real_write_registry = named_workspaces_module._write_registry
            observed_commit = {"value": False}

            def observe_tree(path):
                synced_trees.append(Path(path))
                return real_fsync_tree(path)

            def observe_directory(path):
                synced_directories.append(Path(path))
                return real_fsync_directory(path)

            def verify_before_registry(root_arg, registry):
                if len(registry["workspaces"]) == 2:
                    observed_commit["value"] = True
                    self.assertTrue(any(path.parent.name == "saved_workspaces" for path in synced_trees))
                    self.assertTrue(any(path.name.startswith(".restore-") for path in synced_trees))
                    self.assertIn(studio, synced_directories)
                    self.assertTrue(any(path.name.startswith(".rollback-") for path in synced_directories))
                return real_write_registry(root_arg, registry)

            with (
                patch("backend.named_workspaces._fsync_tree", side_effect=observe_tree),
                patch("backend.named_workspaces._fsync_directory", side_effect=observe_directory),
                patch("backend.named_workspaces._write_registry", side_effect=verify_before_registry),
            ):
                create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )

            self.assertTrue(observed_commit["value"])


if __name__ == "__main__":
    unittest.main()
