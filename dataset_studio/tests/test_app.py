import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.testclient import TestClient

from backend.joint_mapping import CANONICAL_JOINTS
from backend.named_workspaces import create_named_workspace, ensure_workspace_registry


_APP_IMPORT_DIRECTORY = tempfile.TemporaryDirectory()
_APP_IMPORT_CWD = Path.cwd()
try:
    os.chdir(_APP_IMPORT_DIRECTORY.name)
    from backend.app import create_app
finally:
    os.chdir(_APP_IMPORT_CWD)


class ListedExportJobs:
    def __init__(self, jobs: list[dict]):
        self._jobs = jobs

    def list(self) -> list[dict]:
        return self._jobs


def write_dataset(root: Path):
    dataset = root / "demo"
    (dataset / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    (dataset / "data" / "chunk-000").mkdir(parents=True)
    (dataset / "meta" / "info.json").write_text(json.dumps({
        "codebase_version": "v3.0", "fps": 30, "total_episodes": 1, "total_frames": 90,
        "features": {
            "action": {"dtype": "float32", "shape": [6], "names": list(CANONICAL_JOINTS)},
            "observation.state": {"dtype": "float32", "shape": [6], "names": list(CANONICAL_JOINTS)},
            "observation.images.top": {"dtype": "video"},
            "observation.images.wrist": {"dtype": "video"},
        },
    }))
    pq.write_table(pa.table({"episode_index": [0], "length": [90], "task_index": [0]}), dataset / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    pq.write_table(pa.table({"frame_index": list(range(90))}), dataset / "data" / "chunk-000" / "file-000.parquet")
    pq.write_table(pa.table({"task_index": [0], "task": ["Demo task"]}), dataset / "meta" / "tasks.parquet")
    return dataset


class AppTests(unittest.TestCase):
    def test_catalog_and_validation_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root)
            client = TestClient(create_app(root))

            response = client.get("/api/catalog")
            body = response.json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(body["datasets"][0]["name"], "demo")
            self.assertEqual(body["datasets"][0]["episodes"][0]["duration_seconds"], 3.0)
            self.assertEqual(body["datasets"][0]["usable_episodes"], 1)

            validation = client.post("/api/validate", json={
                "choices": [{"dataset_path": str(dataset), "episode_index": 0, "final_prompt": "Edited"}],
                "camera_mappings": {str(dataset): {"observation.images.top": "top"}},
                "required_cameras": ["top"],
                "max_per_task": 1,
            })
            self.assertEqual(validation.status_code, 200)
            self.assertTrue(validation.json()["ok"])

    def test_checkpoint_survives_release_all_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root)
            client = TestClient(create_app(root))
            payload = {"user": "harsh", "dataset_path": str(dataset), "status": "draft", "recipe": {}}

            self.assertEqual(client.post("/api/claims", json=payload).status_code, 200)
            payload["recipe"] = {"episodes": [0]}
            self.assertEqual(client.post("/api/checkpoints", json=payload).status_code, 200)
            self.assertEqual(client.delete("/api/claims/user/harsh").status_code, 200)

            self.assertEqual(client.get("/api/claims").json()["claims"], {})
            shared = client.get("/api/shared-checkpoints").json()["checkpoints"][str(dataset)]
            self.assertEqual(shared["recipe"], {"episodes": [0]})

    def test_settings_history_and_final_camera_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root)
            client = TestClient(create_app(root))
            settings = {
                "output_name": "combined",
                "output_parent": str(root / "exports"),
                "second_camera": "top",
                "max_per_task": 5,
            }

            saved = client.put("/api/settings", json=settings)
            self.assertEqual(saved.status_code, 200)
            self.assertEqual(client.get("/api/settings").json()["required_cameras"], ["wrist", "top"])

            payload = {"user": "harsh", "dataset_path": str(dataset), "status": "draft", "recipe": {"choices": []}}
            client.post("/api/claims", json=payload)
            client.post("/api/checkpoints", json=payload)
            payload["status"] = "approved"
            payload["recipe"]["joint_mapping"] = {
                "action": {name: index for index, name in enumerate(CANONICAL_JOINTS)},
                "observation.state": {name: index for index, name in enumerate(CANONICAL_JOINTS)},
            }
            client.post("/api/checkpoints", json=payload)
            history = client.get("/api/checkpoint-history", params={"dataset_path": str(dataset)}).json()["history"]
            self.assertEqual([item["revision"] for item in history], [1, 2])

            mismatch = client.post("/api/export/jobs", json={"second_camera": "front"})
            self.assertEqual(mismatch.status_code, 409)
            self.assertIn("differs", mismatch.json()["detail"])

    def test_joint_contract_route_and_approval_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root)
            client = TestClient(create_app(root))
            payload = {"user": "harsh", "dataset_path": str(dataset), "status": "draft", "recipe": {"choices": []}}
            client.post("/api/claims", json=payload)

            contract = client.get("/api/datasets/joint-contract", params={"dataset_path": str(dataset)})
            self.assertEqual(contract.status_code, 200)
            self.assertEqual(contract.json()["proposal"]["action"]["gripper.pos"], 5)
            self.assertEqual(client.get("/api/datasets/joint-contract", params={"dataset_path": "/missing"}).status_code, 404)

            payload["status"] = "approved"
            rejected = client.post("/api/checkpoints", json=payload)
            self.assertEqual(rejected.status_code, 422)
            self.assertIn("mapping", str(rejected.json()["detail"]))

    def test_joint_phase_and_bulk_episode_controls_are_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(Path(tmp)))

            html = client.get("/").text
            javascript = client.get("/static/app.js").text

            self.assertIn('id="joints"', html)
            self.assertIn('id="stage-all-episodes"', html)
            self.assertIn('id="clear-stage"', html)
            self.assertIn('id="episode-group-view"', html)
            self.assertIn('id="episode-group-status"', html)
            self.assertIn('id="episode-gallery-controls"', html)
            self.assertIn('id="bulk-task-prompt"', html)
            self.assertIn('id="apply-bulk-task-prompt"', html)
            self.assertIn('id="include-staged-episodes"', html)
            self.assertIn('id="unselect-staged-episodes"', html)
            self.assertIn('id="clear-staged-episodes"', html)
            self.assertIn('id="exclude-checked-included"', html)
            self.assertIn('id="clear-all-included"', html)
            self.assertIn('id="check-included-page"', html)
            self.assertIn('id="included-episodes-view"', html)
            self.assertIn('id="included-page-controls"', html)
            self.assertIn('id="stage-all-episodes" class="quiet" disabled', html)
            self.assertIn("renderJointMapping", javascript)
            self.assertIn("stageAllUsableEpisodes", javascript)
            self.assertIn("clearEpisodeStage", javascript)
            self.assertIn("data-gallery-stage", javascript)
            self.assertIn("data-stage-page", javascript)
            self.assertIn("data-unstage-page", javascript)
            self.assertIn("loadEpisodeGroups", javascript)
            self.assertIn("applyVariantTarget", javascript)
            self.assertIn("applyGroupVariantTarget", javascript)
            self.assertIn("applyClusterCap", javascript)
            self.assertIn("unincludedEpisodeIndices", javascript)
            self.assertIn("balancedClusterSelection(dataset, cluster", javascript)
            self.assertIn("already-included episodes were left out", javascript)
            self.assertIn("Cap new candidates at", javascript)
            self.assertIn("data-group-total-cap", javascript)
            self.assertIn("EPISODE_GALLERY_PAGE_SIZE", javascript)
            self.assertIn("renderEpisodeVariantRows", javascript)
            self.assertIn("renderTasksEditor", javascript)
            self.assertIn("applyBulkTaskPrompt", javascript)
            self.assertIn("commitStagedEpisodes", javascript)
            self.assertIn("commitOneStagedEpisode", javascript)
            self.assertIn("data-include-staged-one", javascript)
            self.assertIn("data-exclude-staged-one", javascript)
            self.assertIn("INCLUDED_EPISODE_PAGE_SIZE", javascript)
            self.assertIn("renderIncludedEpisodes", javascript)
            self.assertIn("data-included-bulk-select", javascript)
            self.assertIn("data-exclude-included-one", javascript)
            self.assertIn("excludeCheckedIncludedEpisodes", javascript)
            self.assertIn("excludeIncludedEpisode", javascript)
            self.assertIn("clearAllIncludedEpisodes", javascript)
            self.assertIn("stagedPromptOverrides", javascript)
            self.assertIn("prepareArchive", javascript)
            self.assertIn("Prepare .tar.gz", javascript)
            self.assertIn("Download .tar.gz", javascript)

    def test_episode_group_route_returns_usable_prompt_variants_without_source_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root)
            info = dataset / "meta" / "info.json"
            before = {
                path.relative_to(dataset): (path.stat().st_mtime_ns, path.stat().st_size)
                for path in dataset.rglob("*")
                if path.is_file()
            }
            client = TestClient(create_app(root))

            response = client.get(
                "/api/datasets/episode-groups",
                params={"dataset_path": str(dataset)},
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["dataset_path"], str(dataset))
            self.assertEqual(body["available_episode_count"], 1)
            self.assertEqual(body["prompt_count"], 1)
            self.assertEqual(body["clusters"][0]["prompts"][0]["text"], "Demo task")
            self.assertEqual(body["clusters"][0]["prompts"][0]["episode_indices"], [0])
            self.assertEqual(
                client.get(
                    "/api/datasets/episode-groups",
                    params={"dataset_path": "/missing"},
                ).status_code,
                404,
            )
            after = {
                path.relative_to(dataset): (path.stat().st_mtime_ns, path.stat().st_size)
                for path in dataset.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            self.assertTrue(info.is_file())

    def test_balance_page_declares_groq_task_group_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(Path(tmp)))

            html = client.get("/").text
            javascript = client.get("/static/app.js").text
            self.assertEqual(client.get("/api/task-groups").json()["groq_prompt_limit"], 400)

            for control_id in (
                "task-group-status",
                "generate-task-groups",
                "balance-view-mode",
                "task-group-view",
            ):
                self.assertIn(f'id="{control_id}"', html)
            for contract in (
                "/api/task-groups",
                "loadTaskGroups",
                "suggestTaskGroupNames",
                "approveTaskGroupName",
                "saveTaskGroupCap",
                "data-group-cap",
            ):
                self.assertIn(contract, javascript)

    def test_task_group_routes_name_and_approve_without_mutating_shared_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            studio = root / ".dataset_studio"
            studio.mkdir()
            checkpoint_file = studio / "dataset_checkpoints.json"
            checkpoint_file.write_text(json.dumps({
                "checkpoints": {
                    "/approved": {
                        "status": "approved",
                        "recipe": {
                            "choices": [
                                {"final_prompt": "Put the red block in the plastic bin"},
                                {"final_prompt": "Place the blue cube into the plastic bin"},
                            ]
                        },
                    },
                    "/draft": {
                        "status": "draft",
                        "recipe": {"choices": [{"final_prompt": "Do not include this draft"}]},
                    },
                },
                "history": {},
            }, indent=2))
            checkpoint_bytes = checkpoint_file.read_bytes()

            def fake_transport(*, payload, **_kwargs):
                clusters = json.loads(payload["messages"][1]["content"])["clusters"]
                return {
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "groups": [{
                                    "cluster_id": cluster["cluster_id"],
                                    "name": "Container object placement",
                                } for cluster in clusters]
                            })
                        }
                    }]
                }

            with patch.dict(os.environ, {"GROQ_API_KEY": "server-secret", "GROQ_TASK_GROUP_MODEL": "test-model"}):
                client = TestClient(create_app(root, task_group_transport=fake_transport))
                initial = client.get("/api/task-groups")
                self.assertEqual(initial.status_code, 200)
                self.assertTrue(initial.json()["groq_configured"])
                self.assertEqual(initial.json()["prompt_count"], 2)

                suggested = client.post("/api/task-groups/suggest")
                self.assertEqual(suggested.status_code, 200)
                cluster = suggested.json()["clusters"][0]
                self.assertEqual(cluster["suggested_name"], "Container object placement")

                approved = client.put(
                    f"/api/task-groups/{cluster['id']}",
                    json={"name": "Objects placed in container"},
                )
                self.assertEqual(approved.status_code, 200)
                self.assertEqual(approved.json()["clusters"][0]["approved_name"], "Objects placed in container")

                capped = client.put(
                    f"/api/task-groups/{cluster['id']}/cap",
                    json={"episode_cap": 1},
                )
                self.assertEqual(capped.status_code, 200)
                self.assertEqual(capped.json()["clusters"][0]["episode_cap"], 1)

            self.assertEqual(checkpoint_file.read_bytes(), checkpoint_bytes)

    def test_task_group_suggestion_requires_server_side_groq_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=True):
                client = TestClient(create_app(Path(tmp)))
                response = client.post("/api/task-groups/suggest")

            self.assertEqual(response.status_code, 503)
            self.assertIn("GROQ_API_KEY", response.json()["detail"])

    def test_workspace_selector_and_destructive_confirmation_controls_are_present(self):
        """Would fail if the named-workspace controls or their guarded transitions disappeared."""
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(Path(tmp)))

            html = client.get("/").text
            javascript = client.get("/static/app.js").text

            for control_id in (
                "workspace-name",
                "workspace-select",
                "switch-workspace",
                "new-workspace",
                "new-workspace-dialog",
                "switch-workspace-dialog",
            ):
                self.assertIn(f'id="{control_id}"', html)
            for contract in (
                "START NEW WORKSPACE",
                "SWITCH WORKSPACE",
                "loadWorkspaceRegistry",
                "startNewWorkspace",
                "switchWorkspace",
                "localStorage.removeItem('dataset-studio-user')",
            ):
                self.assertIn(contract, javascript)
            self.assertIn("Settings and exports are preserved", html)
            self.assertIn("Users, claims, drafts, approvals, and checkpoint history will be replaced", html)

    def test_workspace_frontend_declares_single_flight_save_flush_and_short_dialog_contract(self):
        """Would fail if transitions stopped awaiting saves or dialogs could escape short viewports."""
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(Path(tmp)))

            javascript = client.get("/static/app.js").text
            stylesheet = client.get("/static/phases.css").text

            for contract in (
                "currentSave: null",
                "dirtyVersion: 0",
                "workspaceTransitionPromise: null",
                "workspaceTransitionPending: false",
                "const inFlightSaved = await state.currentSave",
                "if (!inFlightSaved)",
                "if (state.workspaceTransitionPromise) return state.workspaceTransitionPromise",
                "control.disabled = pending",
                "document.body.inert = pending",
                "if (state.workspaceTransitionPending && !allowDuringWorkspaceTransition) return false",
                "if (state.workspaceTransitionPending) return",
                "const previousSucceeded = await previousMutation",
                "if (!previousSucceeded) return false",
                "runWorkspaceMutation",
            ):
                self.assertIn(contract, javascript)
            self.assertNotIn("dialog.close();\n      completeWorkspaceTransition();", javascript)
            self.assertIn("max-block-size: calc(100dvh - 32px)", stylesheet)
            self.assertIn("overflow-y: auto", stylesheet)

    def test_workspace_routes_create_and_restore_checkpoints_after_round_trip_switch(self):
        """Would fail if the workspace routes did not expose Task 1 state changes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root)
            client = TestClient(create_app(root))

            registry = client.get("/api/workspace-registry")
            self.assertEqual(registry.status_code, 200)
            development_id = registry.json()["active_workspace_id"]

            checkpoint = {
                "user": "alice",
                "dataset_path": str(dataset),
                "status": "draft",
                "recipe": {"episodes": [0]},
            }
            self.assertEqual(client.post("/api/claims", json=checkpoint).status_code, 200)
            self.assertEqual(client.post("/api/checkpoints", json=checkpoint).status_code, 200)

            created = client.post("/api/workspaces/new", json={
                "current_name": "Development tests",
                "new_name": "Production curation",
                "confirmation": "START NEW WORKSPACE",
            })
            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["active_workspace"]["name"], "Production curation")

            production_id = created.json()["active_workspace"]["id"]
            self.assertEqual(client.get("/api/shared-checkpoints").json()["checkpoints"], {})
            switched = client.post("/api/workspaces/switch", json={
                "workspace_id": development_id,
                "confirmation": "SWITCH WORKSPACE",
            })
            self.assertEqual(switched.status_code, 200)
            self.assertEqual(
                client.get("/api/shared-checkpoints").json()["checkpoints"][str(dataset)]["recipe"],
                {"episodes": [0]},
            )
            self.assertEqual(client.post("/api/workspaces/switch", json={
                "workspace_id": production_id,
                "confirmation": "SWITCH WORKSPACE",
            }).status_code, 200)

    def test_workspace_routes_map_invalid_requests_and_unknown_switches(self):
        """Would fail if route validation or an unknown workspace ID reached the wrong HTTP branch."""
        with tempfile.TemporaryDirectory() as tmp:
            client = TestClient(create_app(Path(tmp)))

            self.assertEqual(client.post("/api/workspaces/new", json={
                "current_name": "Development tests",
                "new_name": "Production curation",
                "confirmation": "start new workspace",
            }).status_code, 422)
            self.assertEqual(client.post("/api/workspaces/new", json={
                "current_name": "Development tests",
                "new_name": "bad/name",
                "confirmation": "START NEW WORKSPACE",
            }).status_code, 422)
            self.assertEqual(client.post("/api/workspaces/switch", json={
                "workspace_id": "missing",
                "confirmation": "SWITCH WORKSPACE",
            }).status_code, 404)
            self.assertEqual(client.post("/api/workspaces/switch", json={
                "workspace_id": "missing",
                "confirmation": "switch workspace",
            }).status_code, 422)

    def test_workspace_routes_map_snapshot_integrity_failures_to_documented_conflict(self):
        """Would fail if missing or misidentified registered snapshots looked like bad requests."""
        for corruption in ("missing", "wrong-id"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                development_id = ensure_workspace_registry(root)["active_workspace_id"]
                create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )
                snapshot = root / ".dataset_studio" / "saved_workspaces" / development_id
                if corruption == "missing":
                    shutil.rmtree(snapshot)
                else:
                    metadata = json.loads((snapshot / "workspace.json").read_text())
                    metadata["id"] = "different-workspace-id"
                    (snapshot / "workspace.json").write_text(json.dumps(metadata))
                client = TestClient(create_app(root))

                response = client.post("/api/workspaces/switch", json={
                    "workspace_id": development_id,
                    "confirmation": "SWITCH WORKSPACE",
                })

                self.assertEqual(response.status_code, 409)
                self.assertIn("workspace snapshot", response.json()["detail"].lower())
                self.assertIn("manual recovery", response.json()["detail"].lower())

    def test_app_startup_refuses_an_interrupted_workspace_transition_marker(self):
        """Would fail if application startup continued against potentially mixed workspace state."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            studio = root / ".dataset_studio"
            studio.mkdir()
            marker = studio / "workspace_transition.json"
            marker.write_text(json.dumps({
                "operation": "switch",
                "phase": "activating",
                "restore_path": str(studio / ".restore-interrupted"),
                "rollback_path": str(studio / ".rollback-interrupted"),
            }))

            with self.assertRaises(Exception) as caught:
                create_app(root)

            self.assertEqual(type(caught.exception).__name__, "WorkspaceRecoveryRequiredError")
            self.assertIn(str(marker), str(caught.exception))
            self.assertFalse((studio / "jobs").exists())

    def test_running_app_maps_recovery_marker_and_corrupt_registry_to_documented_conflict(self):
        """Would fail if coordinated runtime recovery errors leaked as untyped HTTP 500 responses."""
        for corruption in ("marker", "registry"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                client = TestClient(create_app(root))
                studio = root / ".dataset_studio"
                if corruption == "marker":
                    (studio / "workspace_transition.json").write_text(json.dumps({
                        "operation": "switch",
                        "phase": "committed",
                        "restore_path": str(studio / ".restore-interrupted"),
                        "rollback_path": str(studio / ".rollback-interrupted"),
                    }))
                else:
                    (studio / "workspace_registry.json").write_text(json.dumps({
                        "active_workspace_id": "../../outside",
                        "workspaces": [{
                            "id": "../../outside",
                            "name": "Corrupt",
                            "created_at": "2026-07-27T00:00:00+00:00",
                            "updated_at": "2026-07-27T00:00:00+00:00",
                        }],
                    }))

                response = client.get("/api/workspace-registry")

                self.assertEqual(response.status_code, 409)
                self.assertIn("manual recovery", response.json()["detail"].lower())
                self.assertFalse((root / "outside").exists())

    def test_workspace_routes_block_create_and_switch_for_active_export_jobs(self):
        """Would fail if a workspace change could proceed while an export or archive is active."""
        for status, archive_status in (
            ("queued", "not_requested"),
            ("running", "not_requested"),
            ("cancelling", "not_requested"),
            ("completed", "preparing"),
        ):
            with self.subTest(status=status, archive_status=archive_status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                development_id = ensure_workspace_registry(root)["active_workspace_id"]
                create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )
                job_id = f"blocking-{status}-{archive_status}"
                export_jobs = ListedExportJobs([{
                    "id": job_id,
                    "status": status,
                    "archive_status": archive_status,
                }])
                client = TestClient(create_app(root, export_jobs=export_jobs))

                created = client.post("/api/workspaces/new", json={
                    "current_name": "Production curation",
                    "new_name": "Research curation",
                    "confirmation": "START NEW WORKSPACE",
                })
                switched = client.post("/api/workspaces/switch", json={
                    "workspace_id": development_id,
                    "confirmation": "SWITCH WORKSPACE",
                })
                self.assertEqual(created.status_code, 409)
                self.assertIn(job_id, str(created.json()["detail"]))
                self.assertEqual(switched.status_code, 409)
                self.assertIn(job_id, str(switched.json()["detail"]))

    def test_workspace_routes_allow_completed_ready_and_failed_export_jobs(self):
        """Would fail if terminal export jobs unnecessarily prevented a workspace change."""
        for status, archive_status in (("completed", "ready"), ("failed", "not_requested")):
            with self.subTest(status=status, archive_status=archive_status), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                development_id = ensure_workspace_registry(root)["active_workspace_id"]
                create_named_workspace(
                    root,
                    current_name="Development tests",
                    new_name="Production curation",
                    confirmation="START NEW WORKSPACE",
                )
                jobs = root / ".dataset_studio" / "jobs"
                jobs.mkdir()
                (jobs / f"non-blocking-{status}-{archive_status}.json").write_text(json.dumps({
                    "id": f"non-blocking-{status}-{archive_status}",
                    "status": status,
                    "archive_status": archive_status,
                }))

                client = TestClient(create_app(root))
                created = client.post("/api/workspaces/new", json={
                    "current_name": "Production curation",
                    "new_name": "Research curation",
                    "confirmation": "START NEW WORKSPACE",
                })
                switched = client.post("/api/workspaces/switch", json={
                    "workspace_id": development_id,
                    "confirmation": "SWITCH WORKSPACE",
                })
                self.assertEqual(created.status_code, 200)
                self.assertEqual(switched.status_code, 200)

    def test_workspace_transition_waits_for_export_queue_persistence_then_rechecks_jobs(self):
        """Would fail if a transition could pass its guard while an export plan was being queued."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ensure_workspace_registry(root)
            plan_started = threading.Barrier(2, timeout=2)
            release_plan = threading.Event()
            transition_started = threading.Barrier(2, timeout=2)
            transition_finished = threading.Event()
            jobs: list[dict] = []

            class RacingJobs(ListedExportJobs):
                def __init__(self):
                    super().__init__(jobs)

                def start(self, _plan):
                    job = {
                        "id": "queued-during-transition",
                        "status": "queued",
                        "archive_status": "not_requested",
                    }
                    jobs.append(job)
                    return dict(job)

            def blocked_plan(*_args, **_kwargs):
                plan_started.wait()
                if not release_plan.wait(2):
                    raise AssertionError("export plan release timed out")
                return SimpleNamespace(
                    errors=[],
                    output_path=str(root / "exports" / "assembled_lerobot_v21"),
                    episodes=[],
                )

            client = TestClient(create_app(root, export_jobs=RacingJobs()))
            responses: dict[str, object] = {}

            def start_export():
                responses["export"] = client.post(
                    "/api/export/jobs",
                    json={"second_camera": "front"},
                )

            def transition():
                transition_started.wait()
                responses["transition"] = client.post("/api/workspaces/new", json={
                    "current_name": "Development tests",
                    "new_name": "Production curation",
                    "confirmation": "START NEW WORKSPACE",
                })
                transition_finished.set()

            with patch("backend.app.build_export_plan", side_effect=blocked_plan):
                export_thread = threading.Thread(target=start_export, daemon=True)
                export_thread.start()
                plan_started.wait()
                transition_thread = threading.Thread(target=transition, daemon=True)
                transition_thread.start()
                transition_started.wait()
                transition_completed_before_queue = transition_finished.wait(0.2)
                release_plan.set()
                export_thread.join(2)
                transition_thread.join(2)

            self.assertFalse(export_thread.is_alive() or transition_thread.is_alive())
            self.assertFalse(
                transition_completed_before_queue,
                "workspace transition completed before queued job persistence",
            )
            self.assertEqual(responses["export"].status_code, 200)
            self.assertEqual(responses["transition"].status_code, 409)
            self.assertIn("queued-during-transition", responses["transition"].json()["detail"])

    def test_workspace_transition_waits_for_export_preflight_plan_completion(self):
        """Would fail if a preflight preview could be built across a workspace transition."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ensure_workspace_registry(root)
            plan_started = threading.Barrier(2, timeout=2)
            release_plan = threading.Event()
            transition_started = threading.Barrier(2, timeout=2)
            transition_finished = threading.Event()
            responses: dict[str, object] = {}

            class CompletedPlan:
                @staticmethod
                def to_dict():
                    return {"errors": [], "episodes": []}

            def blocked_plan(*_args, **_kwargs):
                plan_started.wait()
                if not release_plan.wait(2):
                    raise AssertionError("preflight release timed out")
                return CompletedPlan()

            client = TestClient(create_app(root, export_jobs=ListedExportJobs([])))

            def preflight():
                responses["preflight"] = client.post("/api/export/preflight", json={})

            def transition():
                transition_started.wait()
                responses["transition"] = client.post("/api/workspaces/new", json={
                    "current_name": "Development tests",
                    "new_name": "Production curation",
                    "confirmation": "START NEW WORKSPACE",
                })
                transition_finished.set()

            with patch("backend.app.build_export_plan", side_effect=blocked_plan):
                preflight_thread = threading.Thread(target=preflight, daemon=True)
                preflight_thread.start()
                plan_started.wait()
                transition_thread = threading.Thread(target=transition, daemon=True)
                transition_thread.start()
                transition_started.wait()
                transition_completed_before_plan = transition_finished.wait(0.2)
                release_plan.set()
                preflight_thread.join(2)
                transition_thread.join(2)

            self.assertFalse(preflight_thread.is_alive() or transition_thread.is_alive())
            self.assertFalse(
                transition_completed_before_plan,
                "workspace transition completed while preflight still held its workspace view",
            )
            self.assertEqual(responses["preflight"].status_code, 200)
            self.assertEqual(responses["transition"].status_code, 200)

    def test_workspace_transition_waits_for_archive_preparing_persistence_then_rechecks_jobs(self):
        """Would fail if a transition could pass its guard while an archive became preparing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ensure_workspace_registry(root)
            archive_started = threading.Barrier(2, timeout=2)
            release_archive = threading.Event()
            transition_started = threading.Barrier(2, timeout=2)
            transition_finished = threading.Event()
            jobs = [{
                "id": "archive-during-transition",
                "status": "completed",
                "archive_status": "not_requested",
            }]

            class RacingArchiveJobs(ListedExportJobs):
                def prepare_archive(self, job_id):
                    self.assert_job(job_id)
                    archive_started.wait()
                    if not release_archive.wait(2):
                        raise AssertionError("archive release timed out")
                    jobs[0]["archive_status"] = "preparing"
                    return dict(jobs[0])

                @staticmethod
                def assert_job(job_id):
                    if job_id != "archive-during-transition":
                        raise KeyError(job_id)

            client = TestClient(create_app(root, export_jobs=RacingArchiveJobs(jobs)))
            responses: dict[str, object] = {}

            def prepare_archive():
                responses["archive"] = client.post(
                    "/api/export/jobs/archive-during-transition/archive"
                )

            def transition():
                transition_started.wait()
                responses["transition"] = client.post("/api/workspaces/new", json={
                    "current_name": "Development tests",
                    "new_name": "Production curation",
                    "confirmation": "START NEW WORKSPACE",
                })
                transition_finished.set()

            archive_thread = threading.Thread(target=prepare_archive, daemon=True)
            archive_thread.start()
            archive_started.wait()
            transition_thread = threading.Thread(target=transition, daemon=True)
            transition_thread.start()
            transition_started.wait()
            transition_completed_before_preparing = transition_finished.wait(0.2)
            release_archive.set()
            archive_thread.join(2)
            transition_thread.join(2)

            self.assertFalse(archive_thread.is_alive() or transition_thread.is_alive())
            self.assertFalse(
                transition_completed_before_preparing,
                "workspace transition completed before archive preparing persistence",
            )
            self.assertEqual(responses["archive"].status_code, 200)
            self.assertEqual(responses["transition"].status_code, 409)
            self.assertIn("archive-during-transition", responses["transition"].json()["detail"])

    def test_checkpoint_route_holds_one_workspace_operation_through_claim_check_and_save(self):
        """Would fail if checkpoint validation could straddle a transition into another workspace."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = write_dataset(root)
            registry = ensure_workspace_registry(root)
            client = TestClient(create_app(root))
            checkpoint_at_validation = threading.Barrier(2, timeout=2)
            release_checkpoint = threading.Event()
            transition_started = threading.Barrier(2, timeout=2)
            transition_finished = threading.Event()
            responses: dict[str, object] = {}
            payload = {
                "user": "alice",
                "dataset_path": str(dataset),
                "status": "approved",
                "recipe": {"joint_mapping": {}},
            }
            self.assertEqual(client.post("/api/claims", json=payload).status_code, 200)

            def blocked_validation(*_args, **_kwargs):
                checkpoint_at_validation.wait()
                if not release_checkpoint.wait(2):
                    raise AssertionError("checkpoint release timed out")
                return []

            def save_checkpoint_request():
                responses["checkpoint"] = client.post("/api/checkpoints", json=payload)

            def transition():
                transition_started.wait()
                responses["transition"] = client.post("/api/workspaces/new", json={
                    "current_name": "Development tests",
                    "new_name": "Production curation",
                    "confirmation": "START NEW WORKSPACE",
                })
                transition_finished.set()

            with patch("backend.app.validate_joint_mapping", side_effect=blocked_validation):
                checkpoint_thread = threading.Thread(target=save_checkpoint_request, daemon=True)
                checkpoint_thread.start()
                checkpoint_at_validation.wait()
                transition_thread = threading.Thread(target=transition, daemon=True)
                transition_thread.start()
                transition_started.wait()
                transition_completed_before_save = transition_finished.wait(0.2)
                release_checkpoint.set()
                checkpoint_thread.join(2)
                transition_thread.join(2)

            self.assertFalse(checkpoint_thread.is_alive() or transition_thread.is_alive())
            self.assertFalse(
                transition_completed_before_save,
                "workspace transition completed between checkpoint claim validation and persistence",
            )
            self.assertEqual(responses["checkpoint"].status_code, 200)
            self.assertEqual(responses["transition"].status_code, 200)
            previous_snapshot = (
                root
                / ".dataset_studio"
                / "saved_workspaces"
                / registry["active_workspace_id"]
                / "dataset_checkpoints.json"
            )
            previous = json.loads(previous_snapshot.read_text())
            self.assertIn(str(dataset), previous["checkpoints"])
            active = json.loads((root / ".dataset_studio" / "dataset_checkpoints.json").read_text())
            self.assertNotIn(str(dataset), active["checkpoints"])

    def test_completed_export_archive_routes_prepare_and_download_tar_gz(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "exports" / "combined"
            (output / "meta").mkdir(parents=True)
            (output / "meta" / "info.json").write_text("{}")
            jobs = root / ".dataset_studio" / "jobs"
            jobs.mkdir(parents=True)
            job_id = "archive-fixture"
            (jobs / f"{job_id}.json").write_text(json.dumps({
                "id": job_id,
                "status": "completed",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "final_path": str(output),
                "archive_status": "not_requested",
                "archive_path": None,
                "archive_error": None,
            }))
            client = TestClient(create_app(root))

            self.assertEqual(client.get(f"/api/export/jobs/{job_id}/download").status_code, 409)
            self.assertEqual(client.post("/api/export/jobs/missing/archive").status_code, 404)
            started = client.post(f"/api/export/jobs/{job_id}/archive")
            self.assertEqual(started.status_code, 200)
            deadline = time.time() + 5
            while time.time() < deadline:
                job = client.get(f"/api/export/jobs/{job_id}").json()
                if job.get("archive_status") != "preparing":
                    break
                time.sleep(0.02)

            download = client.get(f"/api/export/jobs/{job_id}/download")
            self.assertEqual(download.status_code, 200, job)
            self.assertEqual(download.headers["content-type"], "application/gzip")
            self.assertIn("combined.tar.gz", download.headers["content-disposition"])
            self.assertTrue(download.content.startswith(b"\x1f\x8b"))


if __name__ == "__main__":
    unittest.main()
