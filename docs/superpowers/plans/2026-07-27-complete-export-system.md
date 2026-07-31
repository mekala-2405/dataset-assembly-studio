# Complete Export System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export all approved checkpoints as one verified, balanced LeRobot v2.1 dataset with two normalized cameras.

**Architecture:** A pure planner validates and freezes approved checkpoint inputs. A v2.1 writer handles Parquet/metadata/video normalization. A persisted local job manager runs exports in background threads and exposes progress/cancellation to FastAPI and the UI.

**Tech Stack:** Python, FastAPI, PyArrow, PyAV, HTML, CSS, JavaScript.

## Global Constraints

- Include only approved shared checkpoints.
- Output exactly two cameras: mandatory `wrist` plus a selected second camera.
- Stop on incompatibility; never silently drop approved data.
- Output is LeRobot v2.1 at 30 FPS and 640×480.
- Use manual global maximum episodes per edited task.
- Write to staging and publish only after verification.

### Task 1: Project settings and checkpoint history

**Files:** Create `dataset_studio/backend/settings.py`; modify `dataset_studio/backend/workspaces.py`, `dataset_studio/backend/app.py`; test `dataset_studio/tests/test_settings_history.py`.

**Interfaces:** `load_settings(root)`, `save_settings(root, payload)`, `checkpoint_history(root, dataset_path)`.

- [x] Test persisted settings and immutable checkpoint revision records.
- [x] Implement locked settings and append-only per-dataset history.
- [x] Add GET/PUT settings and GET checkpoint-history routes.

### Task 2: Global planner, balance, and preflight

**Files:** Create `dataset_studio/backend/export_plan.py`; test `dataset_studio/tests/test_export_plan.py`.

**Interfaces:** `build_export_plan(catalog, shared, settings, output_path) -> ExportPlan`; `ExportPlan.errors`, `episodes`, `tasks`, `schemas`.

- [x] Test approved-only aggregation, deterministic task caps, contiguous output/task indices, duplicate detection, camera mapping errors, blank prompts, duration errors, and shape/name mismatch.
- [x] Implement immutable manifest generation and grouped blocking errors.
- [x] Add `/api/export/preflight` returning counts, task balance, manifest preview, and errors.

### Task 3: LeRobot v2.1 Parquet and metadata writer

**Files:** Create `dataset_studio/backend/v21_writer.py`; test `dataset_studio/tests/test_v21_writer.py`.

**Interfaces:** `write_episode_data(plan_episode, output_index_start, destination) -> EpisodeWriteResult`; `finalize_metadata(plan, results, destination)`.

- [x] Test frame/episode/global/task reindexing and exact v2.1 JSONL paths.
- [x] Read selected source rows, slice the source episode, cast action/state float32, regenerate timestamp/index columns, and write one episode Parquet.
- [x] Regenerate tasks, episodes, episode stats, info, aggregate stats, and provenance.

### Task 4: Video normalization

**Files:** Create `dataset_studio/backend/video_export.py`; test `dataset_studio/tests/test_video_export.py`.

**Interfaces:** `normalize_episode_video(source, start, duration, destination, fps=30, size=(640,480), cancel=None)`.

- [x] Build a synthetic video fixture and test output FPS, dimensions, pixel format, and duration.
- [x] Implement seek/decode, nearest-frame resampling, aspect-preserving letterbox, H.264/yuv420p encode, and cancellation.
- [x] Verify both canonical camera videos for every output episode.

### Task 5: Persisted background jobs and final verification

**Files:** Create `dataset_studio/backend/jobs.py`, `dataset_studio/backend/verify_export.py`; modify `dataset_studio/backend/app.py`; test `dataset_studio/tests/test_jobs_export.py`.

**Interfaces:** `ExportJobManager.start(plan)`, `.get(job_id)`, `.cancel(job_id)`, `.list()`; `verify_v21(path, manifest)`.

- [x] Test job states, cancellation, failure retention, successful atomic publish, and verification failures.
- [x] Persist job JSON and manifest before work starts.
- [x] Add list/start/status/cancel routes and staging-to-final publish.

### Task 6: Output, global balance, preflight, and export UI

**Files:** Modify `dataset_studio/frontend/index.html`, `dataset_studio/frontend/app.js`, `dataset_studio/frontend/phases.css`, `dataset_studio/README.md`.

**Interfaces:** Consumes settings, preflight, and export-job APIs.

- [x] Add Start/Output settings with mandatory wrist and selectable second camera.
- [x] Aggregate approved checkpoints in Global Balance and show selected/retained per task.
- [x] Render grouped preflight blockers with remapping guidance.
- [x] Add Final Export confirmation, background progress, cancellation, failure details, and output path.
- [x] Document startup, curation, preflight, export, recovery, and output structure.
