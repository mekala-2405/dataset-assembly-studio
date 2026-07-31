# Named curation workspaces — final fix report

Date: 2026-07-27  
Status: PASS  
Repository mode: no Git; no commits were created.

## Outcome

The final fix wave is complete. All requested critical, important, and minor findings were addressed in one workspace-scoped implementation. The final independent source-only follow-up reported:

- Critical: none
- Important: none
- Minor: none
- Assessment: `Ready: Yes`

Workspace ownership remains exactly:

- `.dataset_studio/claims.json`
- `.dataset_studio/dataset_checkpoints.json`
- `.dataset_studio/workspaces/`

Project settings, jobs, manifests, prepared archives, source datasets, staging directories, and completed exports remain global and preserved. The exact confirmation phrases remain `START NEW WORKSPACE` and `SWITCH WORKSPACE`. No authentication was added.

## Implemented fixes

### Transition commit, cleanup, and interrupted recovery

- Registry persistence defines the commit boundary.
- Snapshot trees, restore trees, active/rollback rename boundaries, registry replacement, and transition markers are fsynced before the marker can be durably removed.
- Cleanup after a committed transition is best-effort and nonfatal.
- Marker unlink or parent-directory fsync failure retains the exact `.restore-*` and `.rollback-*` paths, logs them, returns them in `cleanup_warnings`, and rewrites the marker to `committed`.
- Failed transitions remove the marker durably before deleting recovery paths; marker-removal uncertainty retains both paths.
- Registry-directory sync uncertainty leaves the marker and recovery paths in place and refuses further use.
- Startup and runtime refuse any retained marker with precise recovery instructions and documented HTTP 409 handling.

### One filesystem coordinator

- One `.dataset_studio/workspace_state.lock` coordinates all workspace-owned state.
- Claims, checkpoint/history, and per-user workspace operations hold a shared lock for their full backend operation.
- Create and switch hold the exclusive lock through validation, job-state recheck, snapshot, activation, registry commit, and cleanup.
- Checkpoint claim validation and persistence are covered by one shared operation.
- Export preflight planning, export plan/start through queued persistence, and archive transition through persisted `preparing` state hold the shared lock.
- Deterministic barrier tests prove transitions wait and successful saves remain in the correct workspace.

### Snapshot and path integrity

- Registry JSON shape, active membership, fields, unique IDs/names, and strict 32-character lowercase hex IDs are validated before path use.
- Snapshot paths are confined to `saved_workspaces/`.
- Symlinked or out-of-root `.dataset_studio`, saved-workspace roots, active targets, snapshot targets, metadata, and user JSON entries are refused.
- `workspace.json` is parsed and its ID must match the selected registry entry.
- Claims, shared checkpoint/history, and per-user workspace top-level schemas are validated.
- Legitimately absent legacy targets become canonical empty claims, checkpoints/history, and `workspaces/`.
- Unknown IDs map to 404, request validation to 422, and integrity/recovery conflicts to documented 409 responses.

### Browser transition safety

- Every browser-side workspace mutation—claim, checkpoint save, exclusion, single release, and release-all—is serialized through one tracked promise tail.
- A failed predecessor propagates failure and prevents queued mutations and workspace POSTs.
- Transition submission is single-flight.
- The transition drains the live mutation tail, clears the autosave timer, and persists remaining dirty state before POST.
- Inputs, submit, cancel, header controls, keyboard shortcuts, autosave scheduling, and explicit mutations are frozen while pending.
- Failures keep the dialog open, display the error, and restore controls.
- Success keeps the modal and page inert until reload.

### UX and traceability

- Workspace dialogs have dynamic viewport height limits and vertical scrolling.
- The implementation plan explicitly preserves historical checkboxes and designates the SDD ledger and this report as authoritative.
- README recovery guidance documents root `.restore-*`, root `.rollback-*`, `workspace_transition.json`, saved-workspace `.recovery-*`, symlink refusal, fsync durability, and manual recovery scope.

## TDD evidence

All commands that could import `backend.app` began in a newly created temporary cwd/root and used the absolute path:

```text
PYTHONPATH=/home/ubuntu/harsha/datasets/dataset_studio:/home/ubuntu/harsha/datasets
```

Focused RED/GREEN cycles included:

- Post-commit cleanup injection: RED propagated cleanup errors after commit; GREEN create and switch returned success with consistent registry/active state and retained/logged paths.
- Coordinator interleavings: RED allowed unsafe save/transition ordering; GREEN barrier tests proved old-workspace saves enter the old snapshot and saves begun during transition enter only the new workspace.
- Job TOCTOU: RED allowed transition before queued/preparing persistence; GREEN transition waited and then rejected the active job.
- Snapshot/recovery integrity: RED covered malformed, wrong-ID, missing, and interrupted states; GREEN rejected corruption and canonicalized legitimate legacy absence.
- Checkpoint route coordination: RED allowed validation/persistence to straddle transition; GREEN held one shared operation.
- Browser contracts: RED lacked tracked save, single-flight, pending-control, and short-viewport behavior; GREEN added the contracts and rendered runtime proof.
- Follow-up marker/path/durability cycle: RED produced 3 failures and 1 missing-helper error for pre-commit cleanup, stale retained marker phase, symlink escape, and missing fsync-tree behavior; GREEN passed all focused cases.
- Follow-up mutation-chain cycle: RED lacked predecessor-result propagation; GREEN serialized all workspace mutations and propagated failure.

## Final automated verification

Final suite command, executed from `/tmp/named-workspaces-final-suite-V8WhaL`:

```bash
PYTHONPATH=/home/ubuntu/harsha/datasets/dataset_studio:/home/ubuntu/harsha/datasets \
  /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest discover \
  -s /home/ubuntu/harsha/datasets/dataset_studio/tests -v
```

Result:

```text
Ran 93 tests in 4.726s
OK
```

The only emitted warning was the existing `StarletteDeprecationWarning` for the TestClient/httpx compatibility layer.

## Backend create/switch round trip

Executed from `/tmp/named-workspaces-final-roundtrip-Xwb8fd` with the same absolute `PYTHONPATH`.

Result:

```json
{"global_sentinels": 7, "http_calls": 4, "new_workspace": "New curation", "old_workspace": "Old curation", "temporary_root": "created and removed", "transitions": ["create", "switch-old", "switch-new"]}
```

This covered create, switch to the original workspace, switch back, and seven preserved global sentinels.

## Rendered desktop/mobile QA

The Browser plugin was unavailable, so the documented fallback used headless Google Chrome through the DevTools protocol. The app server imported `backend.app` only after changing to the fresh root `/tmp/named-workspaces-durable-render-root-ZBjchP`; setup and QA used separate fresh temporary working directories.

Evidence JSON:

```text
/tmp/named-workspaces-final-rendered-result.json
```

Passed assertions:

- Desktop 1440×1000: correct app identity, nonblank render, no error overlay, no horizontal overflow.
- New/switch dialogs: exact warnings and phrases, wrong phrase disabled, exact phrase enabled, cancel leaves registry bytes unchanged.
- Single-flight: two submissions returned the same promise and produced one transition request.
- In-flight late edit: first checkpoint contained the original recipe, second checkpoint contained the late edit, and transition waited for both.
- Failed predecessor chain: one checkpoint request, both predecessor and queued tail resolved false, zero workspace POSTs, dialog stayed open, controls and page interactivity restored.
- Failed transition POST: one POST, dialog stayed open, error shown, controls restored.
- Success-to-reload: one POST, zero checkpoint requests during the interval, dialog remained open, page/body remained inert, mutation/autosave gates held, promise remained retained, and reload was scheduled.
- Mobile 390×844: correct identity, names, confirmation behavior, and no horizontal overflow.
- Short viewport 390×560: dialog height 528 within the viewport, `overflow-y: auto`, client height 526, scroll height 628, and actual vertical scrolling.
- Relevant console warnings/errors: 0.
- Runtime exceptions: 0.
- One favicon 404 was explicitly classified as an unrelated browser asset request.

Screenshots:

```text
/tmp/task-4-fix1-desktop-page.png
/tmp/task-4-fix1-desktop-new-confirmed.png
/tmp/task-4-fix1-mobile-switch-confirmed.png
/tmp/task-4-fix1-mobile-short-dialog.png
```

Two earlier QA attempts were harness/infrastructure failures only: one delayed Chrome DevTools startup due to the host keychain, and one DevTools expression accidentally awaited an intentionally unresolved promise. Neither reached a failing product assertion; both checkpoint monitors reported unchanged. The corrected run passed.

## Real checkpoint safety

Protected file:

```text
/home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
```

The file was measured before and after every focused test cycle, full suite, round trip, and rendered QA run. No verification used the real dataset root as its application root.

Final before/after:

```text
SHA-256 before: 022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8
SHA-256 after:  022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8
mtime_ns before: 1785152248424493736
mtime_ns after:  1785152248424493736
CHECKPOINT_SAFETY=UNCHANGED
```

The real file was never reverted because it never changed.

## Files changed

- `dataset_studio/backend/workspace_coordinator.py`
- `dataset_studio/backend/named_workspaces.py`
- `dataset_studio/backend/workspaces.py`
- `dataset_studio/backend/jobs.py`
- `dataset_studio/backend/app.py`
- `dataset_studio/frontend/app.js`
- `dataset_studio/frontend/phases.css`
- `dataset_studio/tests/test_named_workspaces.py`
- `dataset_studio/tests/test_app.py`
- `dataset_studio/README.md`
- `docs/superpowers/plans/2026-07-27-named-curation-workspaces.md`
- `.superpowers/sdd/2026-07-27-named-curation-workspaces/progress.md`

## Remaining concerns

- No known functional issue remains in the requested scope.
- The TestClient/httpx deprecation warning is pre-existing dependency maintenance.
- Rendered QA artifacts are under `/tmp` and are therefore ephemeral; the exact structured findings are preserved in this report.
