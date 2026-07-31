from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .archives import create_export_archive
from .export_plan import ExportPlan
from .video_export import normalize_episode_video
from .workspace_coordinator import workspace_state_lock


TERMINAL_STATES = {"completed", "failed", "cancelled"}


class ExportCancelled(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value):
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    return value


def normalize_episode_cameras(
    episode,
    staging: Path,
    plan: ExportPlan,
    cancel: Callable[[], bool],
    update: Callable[..., None],
    normalizer: Callable = normalize_episode_video,
) -> None:
    cameras = tuple(episode.cameras)
    if not cameras:
        return
    names = [camera.canonical_name for camera in cameras]
    update(
        current_stage="normalizing videos",
        current_camera=" + ".join(names),
        completed_cameras=0,
        total_cameras=len(cameras),
    )

    def normalize(camera):
        if cancel():
            raise ExportCancelled()
        key = f"observation.images.{camera.canonical_name}"
        destination = (
            staging
            / "videos"
            / f"chunk-{episode.output_episode_index // 1000:03d}"
            / key
            / f"episode_{episode.output_episode_index:06d}.mp4"
        )
        return normalizer(
            camera.video_path,
            camera.start_seconds,
            episode.duration_seconds,
            destination,
            fps=plan.fps,
            size=(plan.width, plan.height),
            cancel=cancel,
            preset="veryfast",
            crf=20,
        )

    completed = 0
    remaining = set(names)
    with ThreadPoolExecutor(max_workers=min(2, len(cameras)), thread_name_prefix="camera-export") as executor:
        future_cameras = {executor.submit(normalize, camera): camera for camera in cameras}
        for future in as_completed(future_cameras):
            camera = future_cameras[future]
            future.result()
            completed += 1
            remaining.discard(camera.canonical_name)
            update(
                current_camera=" + ".join(sorted(remaining)) or None,
                completed_cameras=completed,
                total_cameras=len(cameras),
            )


class ExportJobManager:
    def __init__(
        self,
        root: Path,
        exporter: Callable[[ExportPlan, Path, Callable[..., None], Callable[[], bool]], None] | None = None,
    ):
        self.root = Path(root)
        self.jobs_root = self.root / ".dataset_studio" / "jobs"
        self.downloads_root = self.root / ".dataset_studio" / "downloads"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._cancel_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._archive_threads: dict[str, threading.Thread] = {}
        self._exporter = exporter or self._default_exporter
        self._mark_interrupted_jobs()

    def _job_file(self, job_id: str) -> Path:
        return self.jobs_root / f"{job_id}.json"

    def _manifest_file(self, job_id: str) -> Path:
        return self.jobs_root / f"{job_id}.manifest.json"

    def _write(self, job: dict) -> None:
        path = self._job_file(job["id"])
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(job, indent=2, sort_keys=True))
        os.replace(temporary, path)

    def _mark_interrupted_jobs(self) -> None:
        for path in self.jobs_root.glob("*.json"):
            if path.name.endswith(".manifest.json"):
                continue
            try:
                job = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if job.get("status") in {"queued", "running", "cancelling"}:
                job["status"] = "failed"
                job["error"] = "export process stopped before the job finished"
                job["updated_at"] = _now()
                self._write(job)
            if job.get("archive_status") == "preparing":
                job["archive_status"] = "failed"
                job["archive_error"] = "archive preparation stopped before it finished"
                job["updated_at"] = _now()
                self._write(job)

    def start(self, plan: ExportPlan) -> dict:
        with workspace_state_lock(self.root):
            if plan.errors:
                raise ValueError("preflight must pass before export")
            final_path = Path(plan.output_path)
            if final_path.exists():
                raise ValueError(f"output destination already exists: {final_path}")
            job_id = uuid.uuid4().hex
            staging = final_path.parent / f".staging-{job_id}"
            if staging.exists():
                raise ValueError(f"staging destination already exists: {staging}")
            manifest_path = self._manifest_file(job_id)
            manifest_path.write_text(json.dumps(_jsonable(plan), indent=2, sort_keys=True))
            job = {
                "id": job_id,
                "status": "queued",
                "created_at": _now(),
                "updated_at": _now(),
                "manifest_path": str(manifest_path),
                "staging_path": str(staging),
                "final_path": str(final_path),
                "current_dataset": None,
                "current_episode": None,
                "current_camera": None,
                "current_stage": "queued",
                "completed_cameras": 0,
                "total_cameras": 0,
                "completed_episodes": 0,
                "total_episodes": len(plan.episodes),
                "error": None,
                "archive_status": "not_requested",
                "archive_path": None,
                "archive_error": None,
            }
            with self._lock:
                self._write(job)
                event = threading.Event()
                self._cancel_events[job_id] = event
                thread = threading.Thread(target=self._run, args=(job_id, plan, event), daemon=True)
                self._threads[job_id] = thread
                thread.start()
            return self.get(job_id)

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self.get(job_id)
            job.update(changes)
            job["updated_at"] = _now()
            self._write(job)

    def _run(self, job_id: str, plan: ExportPlan, cancel_event: threading.Event) -> None:
        job = self.get(job_id)
        staging = Path(job["staging_path"])
        final = Path(job["final_path"])
        try:
            staging.mkdir(parents=True, exist_ok=False)
            self._update(job_id, status="running", current_stage="preparing output")
            self._exporter(
                plan,
                staging,
                lambda **changes: self._update(job_id, **changes),
                cancel_event.is_set,
            )
            if cancel_event.is_set():
                raise ExportCancelled()
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                raise RuntimeError(f"output destination appeared during export: {final}")
            os.replace(staging, final)
            self._update(
                job_id,
                status="completed",
                completed_episodes=len(plan.episodes),
                current_dataset=None,
                current_episode=None,
                current_camera=None,
                current_stage="completed",
                completed_cameras=0,
                total_cameras=0,
            )
        except ExportCancelled:
            self._update(job_id, status="cancelled", error="export cancelled; staging data retained")
        except Exception as exc:
            if cancel_event.is_set():
                self._update(job_id, status="cancelled", error="export cancelled; staging data retained")
            else:
                self._update(job_id, status="failed", error=str(exc))
        finally:
            with self._lock:
                self._cancel_events.pop(job_id, None)
                self._threads.pop(job_id, None)

    @staticmethod
    def _default_exporter(plan: ExportPlan, staging: Path, update: Callable[..., None], cancel: Callable[[], bool]) -> None:
        from .v21_writer import finalize_metadata, write_episode_data
        from .verify_export import verify_v21

        results = []
        global_index = 0
        for number, episode in enumerate(plan.episodes, start=1):
            if cancel():
                raise ExportCancelled()
            update(
                current_dataset=episode.dataset_name,
                current_episode=episode.source_episode_index,
                current_camera=None,
                current_stage="writing episode data",
                completed_cameras=0,
                total_cameras=len(episode.cameras),
                completed_episodes=number - 1,
            )
            result = write_episode_data(episode, global_index, staging)
            results.append(result)
            length = int(getattr(result, "length", getattr(result, "frame_count", 0)))
            global_index = int(getattr(result, "next_global_index", global_index + length))
            normalize_episode_cameras(episode, staging, plan, cancel, update)
            update(
                completed_episodes=number,
                current_camera=None,
                current_stage="episode complete",
                completed_cameras=len(episode.cameras),
                total_cameras=len(episode.cameras),
            )
        update(current_stage="writing metadata", current_dataset=None, current_episode=None)
        finalize_metadata(plan, results, staging)
        update(current_stage="verifying output")
        verification = verify_v21(staging, _jsonable(plan))
        ok = verification.get("ok") if isinstance(verification, dict) else verification.ok
        errors = verification.get("errors", []) if isinstance(verification, dict) else verification.errors
        if not ok:
            raise RuntimeError("verification failed: " + "; ".join(str(error) for error in errors))

    def get(self, job_id: str) -> dict:
        path = self._job_file(job_id)
        if not path.exists():
            raise KeyError(job_id)
        job = json.loads(path.read_text())
        job.setdefault("archive_status", "not_requested")
        job.setdefault("archive_path", None)
        job.setdefault("archive_error", None)
        return job

    def list(self) -> list[dict]:
        jobs = []
        for path in self.jobs_root.glob("*.json"):
            if path.name.endswith(".manifest.json"):
                continue
            try:
                job = json.loads(path.read_text())
                job.setdefault("archive_status", "not_requested")
                job.setdefault("archive_path", None)
                job.setdefault("archive_error", None)
                jobs.append(job)
            except (json.JSONDecodeError, OSError):
                continue
        return sorted(jobs, key=lambda item: item.get("created_at", ""), reverse=True)

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self.get(job_id)
            if job["status"] in TERMINAL_STATES:
                return job
            event = self._cancel_events.get(job_id)
            if event is None:
                raise ValueError("job is not running in this process")
            event.set()
            self._update(job_id, status="cancelling")
            return self.get(job_id)

    def _expected_archive_path(self, job_id: str) -> Path:
        return self.downloads_root / f"{job_id}.tar.gz"

    def prepare_archive(self, job_id: str) -> dict:
        with workspace_state_lock(self.root):
            with self._lock:
                job = self.get(job_id)
                if job["status"] != "completed":
                    raise ValueError("only a completed export can be archived")
                expected = self._expected_archive_path(job_id)
                if (
                    job.get("archive_status") == "ready"
                    and Path(job.get("archive_path") or "") == expected
                    and expected.is_file()
                ):
                    return job
                if job.get("archive_status") == "preparing":
                    return job
                if expected.is_file():
                    self._update(
                        job_id,
                        archive_status="ready",
                        archive_path=str(expected),
                        archive_error=None,
                    )
                    return self.get(job_id)
                self._update(
                    job_id,
                    archive_status="preparing",
                    archive_path=str(expected),
                    archive_error=None,
                )
                thread = threading.Thread(
                    target=self._prepare_archive,
                    args=(job_id, Path(job["final_path"]), expected),
                    daemon=True,
                    name=f"archive-{job_id[:8]}",
                )
                self._archive_threads[job_id] = thread
                thread.start()
                return self.get(job_id)

    def _prepare_archive(self, job_id: str, source: Path, destination: Path) -> None:
        try:
            create_export_archive(source, destination)
            self._update(
                job_id,
                archive_status="ready",
                archive_path=str(destination),
                archive_error=None,
            )
        except Exception as exc:
            self._update(job_id, archive_status="failed", archive_error=str(exc))
        finally:
            with self._lock:
                self._archive_threads.pop(job_id, None)

    def download_path(self, job_id: str) -> Path:
        job = self.get(job_id)
        if job.get("archive_status") != "ready":
            raise ValueError("archive is not ready")
        expected = self._expected_archive_path(job_id)
        archive_path = Path(job.get("archive_path") or "")
        if archive_path != expected:
            raise ValueError("archive path does not match this export job")
        if not expected.is_file():
            raise ValueError("archive is not ready")
        return expected
