# Autosave, Handoff, and Balance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist every curation action, preserve work across claim handoffs, and expose live episode/task balancing counts.

**Architecture:** A locked shared-checkpoint store complements per-user audit workspaces. The frontend hydrates the latest shared recipe when a dataset opens and uses debounced draft saves with visible status.

**Tech Stack:** FastAPI, JSON with file locks, HTML, CSS, JavaScript.

## Global Constraints

- Claims control write access but never own or delete recipe data.
- Open Dataset begins at Cameras.
- All mutable curation actions auto-save.
- Episodes and Balance expose live selected counts.

### Task 1: Shared checkpoint persistence

**Files:** Modify `dataset_studio/backend/workspaces.py`, `dataset_studio/backend/app.py`, `dataset_studio/tests/test_workspaces.py`.

- [ ] Test that Alice can save, release, and Bob can load the same recipe.
- [ ] Add locked shared checkpoint storage with revision and updated-by fields.
- [ ] Add shared-checkpoint and release-all API routes.

### Task 2: Autosave and claim controls

**Files:** Modify `dataset_studio/frontend/index.html`, `dataset_studio/frontend/app.js`, `dataset_studio/frontend/phases.css`.

- [ ] Add fixed save-status banner and release controls.
- [ ] Hydrate shared recipe when opening a dataset and start in Cameras.
- [ ] Debounce and persist all mutable actions.

### Task 3: Episode and task counts

**Files:** Modify `dataset_studio/frontend/index.html`, `dataset_studio/frontend/app.js`.

- [ ] Show selected episode and distinct edited-task counts in Episodes.
- [ ] Move task cap and grouped counts into Balance.
- [ ] Verify the full backend suite and JavaScript references.
