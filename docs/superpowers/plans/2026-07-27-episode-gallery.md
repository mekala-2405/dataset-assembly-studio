# Episode Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace overlapping episode controls with a gallery and one focused multi-camera episode editor.

**Architecture:** FastAPI supplies path-safe source video streams and cached JPEG thumbnails. Vanilla JavaScript keeps one focused episode index, renders the gallery separately from the detail editor, and lazy-loads all camera videos only on request.

**Tech Stack:** FastAPI, PyAV, HTML, CSS, JavaScript.

## Global Constraints

- Never use a wrist camera as the gallery thumbnail.
- Prefer desk view, then top, then front, then another non-wrist camera.
- Keep full video loading lazy.
- Previous and Next follow the dataset episode order.

### Task 1: Representative camera and thumbnail endpoint

**Files:** Modify `dataset_studio/backend/app.py`; create `dataset_studio/tests/test_gallery.py`.

**Interfaces:** Produces `GET /api/thumbnail?dataset_path=&episode_index=&camera=` returning JPEG or 404.

- [ ] Add a test asserting a wrist camera is not selected when a non-wrist camera exists.
- [ ] Add a cached thumbnail decoder that seeks to the episode start and returns a JPEG.
- [ ] Verify path validation prevents reading outside the selected dataset.

### Task 2: Gallery and focused editor

**Files:** Modify `dataset_studio/frontend/index.html`, `dataset_studio/frontend/app.js`, `dataset_studio/frontend/episodes.css`.

**Interfaces:** Consumes catalog episode video references and preview/thumbnail endpoints.

- [ ] Replace the episode browser and selected tray with `episode-gallery` and `episode-detail`.
- [ ] Render one non-wrist thumbnail, task description, duration, and selection marker per gallery item.
- [ ] Render one focused episode with Previous, Next, editable prompt, and Select/Deselect.

### Task 3: Multi-camera loading and verification

**Files:** Modify `dataset_studio/frontend/app.js`, `dataset_studio/frontend/episodes.css`.

**Interfaces:** `Load all views` creates one video for each indexed source camera.

- [ ] Render every camera independently and show unavailable-camera messages.
- [ ] Ensure navigation stops video playback before changing episodes.
- [ ] Run backend syntax checks, workspace tests, and frontend syntax validation when Node is available.
