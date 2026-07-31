import tempfile
import threading
import time
import unittest
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from backend.export_plan import CameraSource, PlanEpisode
from backend.export_plan import ExportPlan
from backend.jobs import ExportCancelled, ExportJobManager, normalize_episode_cameras


def wait_for(manager: ExportJobManager, job_id: str, terminal: set[str] | None = None) -> dict:
    terminal = terminal or {"completed", "failed", "cancelled"}
    deadline = time.time() + 5
    while time.time() < deadline:
        job = manager.get(job_id)
        if job["status"] in terminal:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job did not finish: {manager.get(job_id)}")


class JobTests(unittest.TestCase):
    def test_completed_job_prepares_and_reuses_lazy_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "exports" / "combined"

            def exporter(_plan, staging, update, cancel):
                (staging / "meta").mkdir(parents=True)
                (staging / "meta" / "info.json").write_text("{}")

            manager = ExportJobManager(root, exporter=exporter)
            completed = wait_for(manager, manager.start(ExportPlan(str(output), ["wrist", "front"]))["id"])
            self.assertEqual(completed["archive_status"], "not_requested")

            preparing = manager.prepare_archive(completed["id"])
            self.assertIn(preparing["archive_status"], {"preparing", "ready"})
            deadline = time.time() + 5
            while time.time() < deadline and manager.get(completed["id"])["archive_status"] == "preparing":
                time.sleep(0.02)
            ready = manager.get(completed["id"])

            self.assertEqual(ready["archive_status"], "ready", ready.get("archive_error"))
            archive = manager.download_path(completed["id"])
            self.assertTrue(archive.is_file())
            modified = archive.stat().st_mtime_ns
            self.assertEqual(manager.prepare_archive(completed["id"])["archive_status"], "ready")
            self.assertEqual(archive.stat().st_mtime_ns, modified)

    def test_archive_rejects_unfinished_jobs_and_guarded_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def exporter(_plan, staging, update, cancel):
                while not cancel():
                    time.sleep(0.002)
                raise ExportCancelled()

            manager = ExportJobManager(root, exporter=exporter)
            job = manager.start(ExportPlan(str(root / "out"), ["wrist", "front"]))
            with self.assertRaisesRegex(ValueError, "completed"):
                manager.prepare_archive(job["id"])
            with self.assertRaisesRegex(ValueError, "not ready"):
                manager.download_path(job["id"])
            manager.cancel(job["id"])
            wait_for(manager, job["id"])

    def test_normalizes_two_episode_cameras_in_parallel_and_reports_progress(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            episode = PlanEpisode(
                dataset_path="/source/a",
                dataset_name="a",
                source_episode_index=7,
                source_fps=30,
                duration_seconds=1.0,
                final_prompt="Pick cube",
                checkpoint_revision=2,
                updated_by="alice",
                output_episode_index=0,
                output_task_index=0,
                source_data_files=(),
                cameras=(
                    CameraSource("wrist", "wrist_left", "/video/wrist.mp4", 0.0),
                    CameraSource("front", "front", "/video/front.mp4", 0.0),
                ),
            )
            plan = ExportPlan(str(staging / "out"), ["wrist", "front"], width=64, height=48)
            barrier = threading.Barrier(2, timeout=1)
            calls = []
            updates = []

            def normalizer(source, start, duration, destination, **kwargs):
                calls.append((source, Path(destination), kwargs))
                barrier.wait()
                return object()

            normalize_episode_cameras(
                episode,
                staging,
                plan,
                cancel=lambda: False,
                update=lambda **changes: updates.append(changes),
                normalizer=normalizer,
            )

            self.assertEqual(len(calls), 2)
            self.assertTrue(all(call[2]["preset"] == "veryfast" for call in calls))
            self.assertTrue(all(call[2]["crf"] == 20 for call in calls))
            self.assertEqual(updates[-1]["completed_cameras"], 2)
            self.assertEqual(updates[-1]["total_cameras"], 2)

    def test_success_is_persisted_and_atomically_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "exports" / "combined"
            plan = ExportPlan(str(output), ["wrist", "front"])

            def exporter(_plan, staging, update, cancel):
                (staging / "meta").mkdir(parents=True)
                (staging / "meta" / "info.json").write_text("{}")
                update(current_episode=1, completed_episodes=1, total_episodes=1)

            manager = ExportJobManager(root, exporter=exporter)
            job = wait_for(manager, manager.start(plan)["id"])

            self.assertEqual(job["status"], "completed")
            self.assertTrue((output / "meta" / "info.json").is_file())
            self.assertFalse(Path(job["staging_path"]).exists())
            self.assertTrue((root / ".dataset_studio" / "jobs" / f"{job['id']}.json").is_file())
            self.assertTrue(Path(job["manifest_path"]).is_file())

    def test_failure_and_cancellation_retain_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def failing(_plan, staging, update, cancel):
                (staging / "partial").write_text("kept")
                raise RuntimeError("verification failed")

            failed_manager = ExportJobManager(root, exporter=failing)
            failed = wait_for(
                failed_manager,
                failed_manager.start(ExportPlan(str(root / "failed"), ["wrist", "front"]))["id"],
            )
            self.assertEqual(failed["status"], "failed")
            self.assertIn("verification failed", failed["error"])
            self.assertTrue((Path(failed["staging_path"]) / "partial").is_file())

            def cancellable(_plan, staging, update, cancel):
                (staging / "partial").write_text("kept")
                for _ in range(500):
                    if cancel():
                        raise ExportCancelled()
                    time.sleep(0.002)

            cancel_manager = ExportJobManager(root, exporter=cancellable)
            job_id = cancel_manager.start(ExportPlan(str(root / "cancelled"), ["wrist", "front"]))["id"]
            cancel_manager.cancel(job_id)
            cancelled = wait_for(cancel_manager, job_id)
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertTrue(Path(cancelled["staging_path"]).exists())

    def test_refuses_a_plan_with_preflight_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = ExportPlan(str(Path(tmp) / "out"), ["wrist", "front"])
            plan.errors.append("blocked")  # the manager only needs truthiness here
            with self.assertRaisesRegex(ValueError, "preflight"):
                ExportJobManager(Path(tmp)).start(plan)

    def test_default_pipeline_writes_normalizes_verifies_and_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_data = root / "source.parquet"
            vectors = pa.array([[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]], type=pa.list_(pa.float32(), 2))
            pq.write_table(
                pa.table(
                    {
                        "action": vectors,
                        "observation.state": vectors,
                        "episode_index": pa.array([7, 7, 7], type=pa.int64()),
                    }
                ),
                source_data,
            )

            def make_video(path: Path, colour: int) -> None:
                with av.open(str(path), "w") as container:
                    stream = container.add_stream("libx264", rate=30)
                    stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
                    for index in range(3):
                        frame = av.VideoFrame.from_ndarray(
                            np.full((48, 64, 3), colour + index, dtype=np.uint8),
                            format="rgb24",
                        )
                        frame.pts, frame.time_base = index, Fraction(1, 30)
                        for packet in stream.encode(frame):
                            container.mux(packet)
                    for packet in stream.encode():
                        container.mux(packet)

            wrist = root / "wrist.mp4"
            front = root / "front.mp4"
            make_video(wrist, 20)
            make_video(front, 40)
            output = root / "exports" / "combined"
            episode = PlanEpisode(
                dataset_path="/source/a",
                dataset_name="a",
                source_episode_index=7,
                source_fps=30,
                duration_seconds=0.1,
                final_prompt="Pick cube",
                checkpoint_revision=2,
                updated_by="alice",
                output_episode_index=0,
                output_task_index=0,
                source_data_files=(str(source_data),),
                cameras=(
                    CameraSource("wrist", "wrist_left", str(wrist), 0.0),
                    CameraSource("front", "front", str(front), 0.0),
                ),
            )
            plan = ExportPlan(
                output_path=str(output),
                required_cameras=["wrist", "front"],
                width=64,
                height=48,
                episodes=[episode],
                tasks=[{"task_index": 0, "task": "Pick cube"}],
                schemas={
                    "action": {"shape": [2], "names": ["a", "b"]},
                    "observation.state": {"shape": [2], "names": ["a", "b"]},
                },
            )

            manager = ExportJobManager(root)
            job = wait_for(manager, manager.start(plan)["id"])

            self.assertEqual(job["status"], "completed", job.get("error"))
            self.assertTrue((output / "meta" / "info.json").is_file())
            self.assertTrue((output / "data/chunk-000/episode_000000.parquet").is_file())
            self.assertEqual(2, len(list((output / "videos").rglob("*.mp4"))))


if __name__ == "__main__":
    unittest.main()
