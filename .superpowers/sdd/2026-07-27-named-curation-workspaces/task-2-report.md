# Task 2 Report: Guarded FastAPI Workspace Routes

## Summary

Implemented the Task 2 FastAPI integration in `dataset_studio/backend/app.py`:

- Added `GET /api/workspace-registry`.
- Added `POST /api/workspaces/new` with `NewWorkspacePayload`.
- Added `POST /api/workspaces/switch` with `SwitchWorkspacePayload`.
- Delegated workspace mutations to Task 1's named-workspace service functions.
- Mapped service validation and confirmation errors to HTTP 422, and an unknown switch target to HTTP 404.
- Added a shared pre-mutation guard for create and switch. It inspects `export_jobs.list()` and returns HTTP 409 with the blocking job ID when a job is queued, running, cancelling, or preparing an archive.

Added route-level tests in `dataset_studio/tests/test_app.py` for registry/create/switch behavior, validation/error mapping, checkpoint round-trip restoration, active-job blocking, and terminal-job allowance. Each test constructs its target API app with `TemporaryDirectory`.

## Exact Tests and Results

Final focused verification:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_named_workspaces -v
```

Result: `Ran 7 tests in 0.073s` — `OK`.

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_app -v
```

Result: `Ran 10 tests in 1.075s` — `OK`.

The app suite emits the existing Starlette TestClient deprecation warning for `httpx`; it has no test failures.

## TDD RED/GREEN Evidence

### Cycle 1: Workspace routes and error mapping

RED command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_app -v
```

Result: `Ran 8 tests` with two expected failures. `GET /api/workspace-registry` returned 404 instead of 200. `POST /api/workspaces/new` returned 405 instead of 422; the pre-existing `GET /api/workspaces/{user}` route matches the path but does not accept POST, so the observed status differs from the brief's anticipated 404. This confirmed the new routes were absent.

GREEN command: same command.

Result: `Ran 8 tests in 0.753s` — `OK` after adding payload models, routes, and error mapping.

### Cycle 2: Active export-job guard

RED command: same Task 2 command.

Result: `Ran 10 tests` with two expected subtest failures. Both a `running`/`not_requested` job and a `completed`/`preparing` job allowed workspace creation with HTTP 200 rather than the required 409. This confirmed no guard existed.

GREEN command: same Task 2 command.

Result: `Ran 10 tests in 1.088s` — `OK` after adding the shared guard that reads `export_jobs.list()` before either workspace mutation.

## Files Changed

- `dataset_studio/backend/app.py`
- `dataset_studio/tests/test_app.py`
- `.superpowers/sdd/2026-07-27-named-curation-workspaces/task-2-report.md`

## Self-Review

- Confirmed the only intentional edits were the two permitted Task 2 source/test files plus this report.
- Confirmed the routes use the Task 1 service functions rather than duplicating workspace state logic.
- Confirmed all `ValueError` cases on create map to 422; switch maps exactly `workspace does not exist` to 404 and other validation/confirmation errors to 422.
- Confirmed the active-job guard runs before both create and switch and neither changes nor cancels a job.
- Confirmed blocking tests include the job ID in each 409 response and that completed/ready and failed jobs remain allowed.
- Confirmed the round-trip test restores saved checkpoints through the HTTP API.
- Confirmed the two required focused suites pass on a fresh final run.

## Concerns

`ExportJobManager` has pre-existing startup recovery that changes persisted `queued`, `running`, `cancelling`, and `preparing` records to failed when an app starts. The guard correctly reads `export_jobs.list()` for live jobs, but the active-job tests patch only that recovery hook so records persisted before app creation represent live jobs. Changing restart-recovery semantics would require modifying `backend/jobs.py`, which is outside Task 2's allowed file scope.

Additionally, `backend.app` has a pre-existing module-level `app = create_app(Path.cwd())`. Importing it while running the required test command from this workspace invoked legacy workspace migration against the real `.dataset_studio`; its `dataset_checkpoints.json` timestamp changed to 16:33 IST. No cleanup or revert was attempted, because that would further mutate user data without authorization.

## Fix Round 1: Test Isolation and Guard Fixtures

### Summary

- Isolated the `backend.app` import in `test_app.py`: the module now enters a module-owned `TemporaryDirectory` before importing `create_app`, then restores the original cwd. This contains the module-level application's `create_app(Path.cwd())` side effect while the test command itself is still launched from `/home/ubuntu/harsha/datasets`.
- Added an optional `export_jobs` argument to `create_app`. Production retains the default `ExportJobManager(dataset_root)`; tests inject a narrow in-process object whose real boundary is `list()`.
- Replaced the restart-recovery patch with the injected live-job list fixture. Tests no longer suppress `ExportJobManager._mark_interrupted_jobs`.
- Added guard coverage for `queued` and `cancelling`, alongside `running` and archive `preparing`.
- Added invalid switch-confirmation coverage for HTTP 422.

### TDD RED/GREEN Evidence

Before RED, from `/home/ubuntu/harsha/datasets`:

```text
SHA-256: 022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8
mtime:   1785150201 (2026-07-27 16:33:21.746959785 +0530)
```

RED command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_app -v
```

Result: `Ran 10 tests` with four expected errors, one for each injected active-job state (`queued`, `running`, `cancelling`, and archive `preparing`). Each error was `TypeError: create_app() got an unexpected keyword argument 'export_jobs'`, confirming the narrow test dependency boundary did not yet exist.

GREEN command: same Task 2 command.

Result: `Ran 10 tests in 0.977s` — `OK`. The new guard fixture produced 409 responses carrying each blocking job ID; completed/ready and failed jobs remained allowed.

### Fresh Focused Verification and Safety Evidence

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_named_workspaces -v
```

Result: `Ran 7 tests in 0.059s` — `OK`.

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_app -v
```

Result: `Ran 10 tests in 1.032s` — `OK`.

After the GREEN run and again after both fresh focused suites, the real file remained exactly:

```text
SHA-256: 022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8
mtime:   1785150201 (2026-07-27 16:33:21.746959785 +0530)
```

The byte checksum and mtime match the values captured before RED.

### Fix Round 1 Self-Review

- The import isolation happens before `backend.app` is imported; the original cwd is restored immediately afterward.
- `create_app` preserves production behavior when no manager is injected.
- The injected fixture does not patch production restart recovery and only supplies the route guard's required `list()` boundary.
- The active-job guard still performs no job mutation or cancellation.
- The final required Task 1 and Task 2 suites passed, and the real checkpoint file's bytes and mtime remained unchanged during this fix round.
