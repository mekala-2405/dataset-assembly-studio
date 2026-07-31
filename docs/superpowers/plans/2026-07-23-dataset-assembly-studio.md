# Dataset Assembly Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web app that assembles validated SO-101 episodes into a balanced LeRobot v2.1 dataset.

**Architecture:** A FastAPI service inventories and validates nested LeRobot roots, serves previews and selection state, and runs export jobs. A local React UI drives catalog filtering, camera mapping, prompt edits, balancing, and export progress.

**Tech Stack:** Python, FastAPI, PyArrow, FFmpeg, React, Vite, TypeScript.

## Global Constraints

- Scan every nested `meta/info.json` below `/home/ubuntu/harsha/datasets`.
- Exclude episodes shorter than two seconds.
- Output LeRobot v2.1, 30 FPS, 640x480 video.
- Preserve source provenance and balance using edited final task prompts.

---

### Task 1: Catalog and structural validation

**Files:** Create `dataset_studio/backend/catalog.py`, `dataset_studio/tests/test_catalog.py`.

- [ ] Write failing tests for nested root discovery, invalid Parquet exclusion, derived-name marking, duration filtering, and count consistency.
- [ ] Implement metadata discovery and per-episode validation results.
- [ ] Run `pytest dataset_studio/tests/test_catalog.py -v`.

### Task 2: Export recipe and balancing

**Files:** Create `dataset_studio/backend/recipe.py`, `dataset_studio/tests/test_recipe.py`.

- [ ] Write failing tests for canonical camera mapping, omitted cameras, prompt edits, required-camera rejection, and seeded task balancing.
- [ ] Implement serializable selection recipes and deterministic balancing by final prompt.
- [ ] Run `pytest dataset_studio/tests/test_recipe.py -v`.

### Task 3: LeRobot v2.1 exporter

**Files:** Create `dataset_studio/backend/exporter.py`, `dataset_studio/tests/test_exporter.py`.

- [ ] Write failing tests for reindexing, v2.1 metadata, provenance records, and minimum-duration enforcement.
- [ ] Implement dry-run validation, FFmpeg normalization, output writing, and final validation.
- [ ] Run `pytest dataset_studio/tests/test_exporter.py -v`.

### Task 4: API and local UI

**Files:** Create `dataset_studio/backend/app.py`, `dataset_studio/frontend/`.

- [ ] Write failing API tests for catalog, preview, recipe, dry-run, and export-job endpoints.
- [ ] Implement FastAPI routes and the React catalog, preview, mapping, summary, and export screens.
- [ ] Run backend tests and the frontend production build.

### Task 5: End-to-end verification

**Files:** Create `dataset_studio/tests/test_e2e_export.py`, `dataset_studio/README.md`.

- [ ] Build a fixture dataset with valid, invalid, short, and derived sources.
- [ ] Verify export excludes invalid/short episodes, balances edited tasks, and is readable as LeRobot v2.1.
- [ ] Document local startup and export workflow.
