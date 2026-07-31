# Task 3 Report — Workspace selector and destructive confirmation dialogs

## Delivered

Added the named-workspace header selector, native confirmation dialogs for starting and switching workspaces, guarded transition requests, and responsive paper/leaf/red dialog styling. The implementation consumes the Task 2 registry and transition routes without changing backend behavior or the existing phase workflow.

## Files changed

- `dataset_studio/frontend/index.html`
  - Added active-workspace display, selector, Switch action, and Save & start new action.
  - Added fully labelled native `<dialog>` forms for new/switch confirmation, destructive-scope warning panels, Cancel controls, and in-dialog live error regions.
- `dataset_studio/frontend/app.js`
  - Added registry state/rendering through `loadWorkspaceRegistry()` during initial catalog loading.
  - Added exact-phrase disabled-state guards, dirty-checkpoint persistence before both POSTs, API errors retained in the open dialog, local profile removal, saved status, and delayed reload after success.
- `dataset_studio/frontend/phases.css`
  - Added workspace control and dialog styling using existing paper/leaf/red variables and responsive single-column layouts below 520px.
- `dataset_studio/tests/test_app.py`
  - Added the Task 3 static frontend contract test.

## RED/GREEN evidence

### RED

Command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_app.AppTests.test_workspace_selector_and_destructive_confirmation_controls_are_present -v
```

Observed output:

```text
FAIL
AssertionError: 'id="workspace-name"' not found
Ran 1 test in 0.045s
FAILED (failures=1)
```

This failed because the Task 3 controls did not exist yet.

### GREEN

Command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_app.AppTests.test_workspace_selector_and_destructive_confirmation_controls_are_present -v
```

Observed output:

```text
test_workspace_selector_and_destructive_confirmation_controls_are_present ... ok
Ran 1 test in 0.052s
OK
```

## Verification

Command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_app -v
```

Observed output:

```text
Ran 11 tests in 1.042s
OK
```

Command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces dataset_studio.tests.test_workspaces -v
```

Observed output:

```text
Ran 11 tests in 0.063s
OK
```

Final full-suite command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest discover -s dataset_studio/tests -v
```

Observed output:

```text
Ran 70 tests in 2.028s
OK
```

The test process emitted the pre-existing FastAPI/Starlette `TestClient` deprecation warning about the installed `httpx`; no test failures or implementation warnings were reported.

## Accessibility and responsive decisions

- Used semantic native dialogs, labelled inputs, native buttons/selects, `aria-live` status/error regions, and explicit Cancel buttons. Native dialog Escape/focus behavior is retained; opening a dialog puts focus in its first actionable field.
- Both confirm buttons remain disabled unless their exact confirmation phrase is entered. Switching also remains disabled until the selected ID differs from the active ID.
- Each destructive dialog states the current/destination context where applicable and clearly distinguishes reset scope from preserved settings/exports.
- Dialog width is constrained to `min(620px, calc(100vw - 32px))`. At 520px and below, workspace controls, dialog transitions, and dialog action buttons stack or flex-wrap so they do not overlap at 390px.
- No new motion was introduced; the existing global reduced-motion rule continues to cover the added controls.

## Self-review

- Confirmed the registry is loaded during initial loading and populates active name/selector state.
- Confirmed both transitions cancel pending autosave and persist an open dirty dataset before the destructive POST; a save failure stays in the dialog and prevents the request.
- Confirmed POST failures render in the still-open dialog, and success removes `dataset-studio-user`, shows the specified saved status, then reloads after 500ms.
- Confirmed warning copy exactly includes both required preserved and replaced scope statements.
- Confirmed no unrelated phase workflow or backend files were changed.

## Concerns

- A standalone JavaScript parser check could not run because this environment has no `node`, `nodejs`, `deno`, `bun`, or `qjs` executable. The attempted command and output were:

```bash
node --check dataset_studio/frontend/app.js
```

```text
/bin/bash: line 1: node: command not found
```

The FastAPI static frontend contract test and all 70 backend tests completed successfully. No browser automation runtime was available for a rendered visual check.
