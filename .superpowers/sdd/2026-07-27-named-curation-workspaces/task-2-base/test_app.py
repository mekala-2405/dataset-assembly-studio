import json
import tempfile
import time
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.joint_mapping import CANONICAL_JOINTS


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
            self.assertIn('id="select-all-episodes"', html)
            self.assertIn('id="clear-episodes"', html)
            self.assertIn('id="select-all-episodes" class="quiet" disabled', html)
            self.assertIn("renderJointMapping", javascript)
            self.assertIn("selectAllUsableEpisodes", javascript)
            self.assertIn("clearEpisodeSelection", javascript)
            self.assertIn("prepareArchive", javascript)
            self.assertIn("Prepare .tar.gz", javascript)
            self.assertIn("Download .tar.gz", javascript)

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
