from __future__ import annotations

from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .catalog import scan_catalog
from .export_plan import build_export_plan
from .jobs import ExportJobManager
from .joint_mapping import build_joint_contract, validate_joint_mapping
from .named_workspaces import create_named_workspace, ensure_workspace_registry, switch_named_workspace
from .recipe import EpisodeChoice, validate_and_balance
from .preview import choose_thumbnail_camera, thumbnail_jpeg
from .settings import load_settings, save_settings
from .workspaces import checkpoint_history, claim_dataset, load_claims, load_shared_checkpoints, load_workspace, migrate_legacy_workspaces, release_all_claims, release_dataset, save_checkpoint


class ChoicePayload(BaseModel):
    dataset_path: str
    episode_index: int
    final_prompt: str


class ValidationPayload(BaseModel):
    choices: list[ChoicePayload]
    camera_mappings: dict[str, dict[str, str | None]]
    required_cameras: list[str]
    max_per_task: int | None = None


class CheckpointPayload(BaseModel):
    user: str
    dataset_path: str
    status: str
    recipe: dict = {}


class SettingsPayload(BaseModel):
    output_name: str
    output_parent: str
    second_camera: str
    max_per_task: int | None = None


class PreflightPayload(BaseModel):
    second_camera: str | None = None


class StartExportPayload(BaseModel):
    second_camera: str


class NewWorkspacePayload(BaseModel):
    current_name: str
    new_name: str
    confirmation: str


class SwitchWorkspacePayload(BaseModel):
    workspace_id: str
    confirmation: str


def create_app(dataset_root: Path) -> FastAPI:
    migrate_legacy_workspaces(dataset_root)
    app = FastAPI(title="Dataset Assembly Studio")
    static_root = Path(__file__).parent.parent / "frontend"
    export_jobs = ExportJobManager(dataset_root)
    app.mount("/static", StaticFiles(directory=static_root), name="static")

    @lru_cache(maxsize=1)
    def catalog():
        return scan_catalog(dataset_root)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/catalog")
    def get_catalog(refresh: bool = False) -> dict:
        if refresh:
            catalog.cache_clear()
        datasets = catalog()
        serialized = []
        for dataset in datasets:
            item = asdict(dataset)
            item["usable_episodes"] = dataset.usable_episodes
            serialized.append(item)
        return {
            "datasets": serialized,
            "summary": {
                "datasets": len(datasets),
                "valid": sum(dataset.valid for dataset in datasets),
                "usable_episodes": sum(dataset.usable_episodes for dataset in datasets),
            },
        }

    @app.post("/api/validate")
    def validate(payload: ValidationPayload) -> dict:
        result = validate_and_balance(
            catalog(),
            [EpisodeChoice(**choice.model_dump()) for choice in payload.choices],
            payload.camera_mappings,
            payload.required_cameras,
            payload.max_per_task,
        )
        return {"ok": result.ok, "errors": result.errors, "choices": [asdict(choice) for choice in result.choices], "task_counts": result.task_counts}

    @app.get("/api/workspaces/{user}")
    def get_workspace(user: str) -> dict:
        return load_workspace(dataset_root, user)

    @app.get("/api/workspace-registry")
    def get_workspace_registry() -> dict:
        return ensure_workspace_registry(dataset_root)

    def reject_workspace_change_during_active_job() -> None:
        blocking_job = next(
            (
                job
                for job in export_jobs.list()
                if job["status"] in {"queued", "running", "cancelling"}
                or job.get("archive_status") == "preparing"
            ),
            None,
        )
        if blocking_job is not None:
            raise HTTPException(409, f"workspace changes are blocked by export job {blocking_job['id']}")

    @app.post("/api/workspaces/new")
    def new_workspace(payload: NewWorkspacePayload) -> dict:
        reject_workspace_change_during_active_job()
        try:
            return create_named_workspace(dataset_root, **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.post("/api/workspaces/switch")
    def switch_workspace(payload: SwitchWorkspacePayload) -> dict:
        reject_workspace_change_during_active_job()
        try:
            return switch_named_workspace(dataset_root, **payload.model_dump())
        except ValueError as exc:
            status_code = 404 if str(exc) == "workspace does not exist" else 422
            raise HTTPException(status_code, str(exc))

    @app.get("/api/claims")
    def claims() -> dict:
        return load_claims(dataset_root)

    @app.get("/api/shared-checkpoints")
    def shared_checkpoints() -> dict:
        return load_shared_checkpoints(dataset_root)

    @app.get("/api/checkpoint-history")
    def get_checkpoint_history(dataset_path: str) -> dict:
        return {"dataset_path": dataset_path, "history": checkpoint_history(dataset_root, dataset_path)}

    @app.get("/api/settings")
    def get_settings() -> dict:
        return load_settings(dataset_root)

    @app.put("/api/settings")
    def put_settings(payload: SettingsPayload) -> dict:
        try:
            return save_settings(dataset_root, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/datasets/joint-contract")
    def joint_contract(dataset_path: str) -> dict:
        dataset = next((item for item in catalog() if item.path == dataset_path), None)
        if dataset is None:
            raise HTTPException(404, "dataset not found")
        try:
            return build_joint_contract(Path(dataset.path)).to_dict()
        except Exception as exc:
            raise HTTPException(422, f"joint metadata is unreadable: {exc}")

    @app.post("/api/export/preflight")
    def export_preflight(payload: PreflightPayload | None = None) -> dict:
        settings = load_settings(dataset_root)
        if payload and payload.second_camera is not None:
            settings["second_camera"] = payload.second_camera
            settings["required_cameras"] = ["wrist", payload.second_camera]
        destination = Path(settings["output_parent"]) / settings["output_name"]
        plan = build_export_plan(catalog(), load_shared_checkpoints(dataset_root), settings, destination)
        return plan.to_dict()

    @app.get("/api/export/jobs")
    def list_export_jobs() -> dict:
        return {"jobs": export_jobs.list()}

    @app.get("/api/export/jobs/{job_id}")
    def get_export_job(job_id: str) -> dict:
        try:
            return export_jobs.get(job_id)
        except KeyError:
            raise HTTPException(404, "export job not found")

    @app.post("/api/export/jobs")
    def start_export_job(payload: StartExportPayload) -> dict:
        settings = load_settings(dataset_root)
        if payload.second_camera != settings["second_camera"]:
            raise HTTPException(
                409,
                "final camera choice differs from Output settings; save the new choice, remap approved datasets, and rerun Preflight",
            )
        destination = Path(settings["output_parent"]) / settings["output_name"]
        plan = build_export_plan(catalog(), load_shared_checkpoints(dataset_root), settings, destination)
        if plan.errors:
            raise HTTPException(422, {"message": "preflight failed", "errors": [asdict(error) for error in plan.errors]})
        try:
            return export_jobs.start(plan)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.delete("/api/export/jobs/{job_id}")
    def cancel_export_job(job_id: str) -> dict:
        try:
            return export_jobs.cancel(job_id)
        except KeyError:
            raise HTTPException(404, "export job not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/export/jobs/{job_id}/archive")
    def prepare_export_archive(job_id: str) -> dict:
        try:
            return export_jobs.prepare_archive(job_id)
        except KeyError:
            raise HTTPException(404, "export job not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/export/jobs/{job_id}/download")
    def download_export_archive(job_id: str):
        try:
            path = export_jobs.download_path(job_id)
            job = export_jobs.get(job_id)
        except KeyError:
            raise HTTPException(404, "export job not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        return FileResponse(
            path,
            media_type="application/gzip",
            filename=f"{Path(job['final_path']).name}.tar.gz",
        )

    @app.post("/api/claims")
    def claim(payload: CheckpointPayload) -> dict:
        try:
            return claim_dataset(dataset_root, payload.user, payload.dataset_path)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.delete("/api/claims")
    def release(payload: CheckpointPayload) -> dict:
        try:
            return release_dataset(dataset_root, payload.user, payload.dataset_path)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.delete("/api/claims/user/{user}")
    def release_all(user: str) -> dict:
        return release_all_claims(dataset_root, user)

    @app.post("/api/checkpoints")
    def checkpoint(payload: CheckpointPayload) -> dict:
        owner = load_claims(dataset_root)["claims"].get(payload.dataset_path)
        if owner != payload.user:
            raise HTTPException(409, "claim this dataset before saving a checkpoint")
        if payload.status == "approved":
            dataset = next((item for item in catalog() if item.path == payload.dataset_path), None)
            if dataset is None:
                raise HTTPException(404, "dataset not found")
            try:
                errors = validate_joint_mapping(
                    payload.recipe.get("joint_mapping") or {},
                    build_joint_contract(Path(dataset.path)),
                )
            except Exception as exc:
                raise HTTPException(422, f"joint metadata is unreadable: {exc}")
            if errors:
                raise HTTPException(422, {"message": "joint mapping is incomplete", "errors": errors})
        return save_checkpoint(dataset_root, payload.user, payload.dataset_path, payload.status, payload.recipe)

    @app.get("/api/preview")
    def preview(dataset_path: str, episode_index: int, camera: str):
        dataset = next((item for item in catalog() if item.path == dataset_path), None)
        if dataset is None or camera not in dataset.cameras:
            raise HTTPException(404, "dataset or camera not found")
        episode = next((item for item in dataset.episodes if item.index == episode_index), None)
        path = Path(episode.video_files.get(camera, "")) if episode else None
        if path is None or not path.is_file() or dataset_root not in path.parents:
            raise HTTPException(404, "no indexed preview for this episode")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/thumbnail")
    def thumbnail(dataset_path: str, episode_index: int):
        dataset = next((item for item in catalog() if item.path == dataset_path), None)
        episode = next((item for item in dataset.episodes if item.index == episode_index), None) if dataset else None
        if dataset is None or episode is None:
            raise HTTPException(404, "dataset or episode not found")
        camera = choose_thumbnail_camera(dataset.cameras, set(episode.video_files))
        if camera is None:
            raise HTTPException(404, "no non-wrist thumbnail camera available")
        path = Path(episode.video_files[camera])
        if not path.is_file() or dataset_root not in path.parents:
            raise HTTPException(404, "thumbnail source not found")
        try:
            body = thumbnail_jpeg(str(path), episode.video_starts.get(camera, 0.0))
        except Exception as exc:
            raise HTTPException(422, f"thumbnail decode failed: {exc}")
        return Response(body, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/")
    def index():
        return FileResponse(static_root / "index.html")

    return app


app = create_app(Path.cwd())
