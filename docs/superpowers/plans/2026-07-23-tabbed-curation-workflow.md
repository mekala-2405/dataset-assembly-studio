# Tabbed Curation Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Dataset Assembly Studio into a freely navigable, phase-based curation workspace with video review during episode selection.

**Architecture:** The existing FastAPI catalog and validation APIs remain the source of truth. The no-build frontend holds a single in-memory recipe state, renders one phase at a time, and derives tab badges from catalog, mapping, selection, and validation state.

**Tech Stack:** FastAPI, PyArrow, OpenCV/PyAV for source video inspection, HTML, CSS, vanilla JavaScript.

## Global Constraints

- Keep all eight phases freely navigable: Sources, Output, Cameras, Episodes, Tasks, Balance, Preflight, Export.
- Exclude source episodes shorter than two seconds.
- Display source video preview at the episode-selection step.
- Output remains LeRobot v2.1 at 30 FPS and 640×480.

### Task 1: Phase shell and recipe state

**Files:** Modify `dataset_studio/frontend/index.html`, `dataset_studio/frontend/app.js`, `dataset_studio/frontend/style.css`.

- [ ] Create accessible phase-tab controls and one named panel per phase.
- [ ] Keep tabs enabled; compute badges for selected episodes, camera mapping gaps, and preflight errors.
- [ ] Verify static assets load through FastAPI and keyboard navigation selects a tab.

### Task 2: Source, camera, episode, task, and balance panels

**Files:** Modify `dataset_studio/frontend/app.js`, `dataset_studio/frontend/style.css`.

- [ ] Render the 26 source-folder groups in Sources.
- [ ] Render source camera mapping controls in Cameras using the shared recipe state.
- [ ] Render selectable individual episodes, editable prompts, and live task/balance summaries in their dedicated panels.
- [ ] Verify a selection and prompt change updates all relevant panels without resetting state.

### Task 3: Safe source video preview

**Files:** Modify `dataset_studio/backend/catalog.py`, `dataset_studio/backend/app.py`; create `dataset_studio/tests/test_preview.py`.

- [ ] Write a failing API test for a preview response constrained to an indexed source dataset/video file.
- [ ] Add indexed video references to episode metadata and a path-safe preview endpoint.
- [ ] Display mapped camera previews with source task and timestamps in Episodes.
- [ ] Run the complete test suite.

### Task 4: Preflight and export handoff

**Files:** Modify `dataset_studio/frontend/app.js`, `dataset_studio/frontend/style.css`.

- [ ] Render validation errors in Preflight with links to the relevant phase.
- [ ] Render the final recipe summary in Export and keep exporting disabled until preflight passes.
- [ ] Verify all pages retain the current recipe when moving between tabs.
