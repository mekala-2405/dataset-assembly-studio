# Task 4 report: documentation and complete verification

## Status

DONE. Task 4 documentation and verification items were completed from fresh evidence. No production code was changed.

## Documentation

Added `Named curation workspaces` to `dataset_studio/README.md`. It documents the workspace-owned state (`claims.json`, `dataset_checkpoints.json`, and `workspaces/`) versus preserved global state; exact create and switch phrases; active-job blocking; snapshot location; browser editor reset to `operator`; and manual restoration from `.dataset_studio/saved_workspaces/.recovery-*` directories.

## Full test suite

Command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest discover -s dataset_studio/tests -v
```

Result: `Ran 70 tests in 2.244s` and `OK` (zero failures).

## Rendered QA

The Browser plugin was absent. Node, Playwright, and `package.json` were also absent, so the allowed fallback used `/usr/bin/google-chrome` headless with the Chrome DevTools Protocol; no dependency was installed. The served application used an isolated temporary dataset root and the browser only opened dialogs, edited form fields, and cancelled.

| Check | Desktop 1440x1000 | Emulated mobile 390x844 |
| --- | --- | --- |
| Identity and nonblank content | `Dataset Assembly Studio`; meaningful rendered content | `Dataset Assembly Studio`; meaningful rendered content |
| Error overlay | None | None |
| Horizontal overflow | `scrollWidth=1440`, `innerWidth=1440` | `scrollWidth=390`, `innerWidth=390` |
| New dialog | Warning present; initially disabled; wrong phrase disabled; `START NEW WORKSPACE` enabled; Cancel left registry unchanged | N/A |
| Switch dialog | N/A | Current `Browser destination`, destination `Browser origin`; initially disabled; wrong phrase disabled; `SWITCH WORKSPACE` enabled; Cancel left registry unchanged |
| Relevant console/runtime errors | None | None |

Chrome logged one ignored, non-application asset request: a browser-initiated `GET /favicon.ico` received 404. It did not affect the workspace UI or its runtime behavior.

Screenshots saved outside the repository:

- `/tmp/task-4-desktop-page.png`
- `/tmp/task-4-desktop-new-confirmed.png`
- `/tmp/task-4-mobile-switch-confirmed.png`

## Temporary-root backend round trip

Using FastAPI HTTP routes against a `TemporaryDirectory` root:

1. Created `New curation` from `Old curation`; the new active workspace was empty.
2. Wrote distinct new-workspace claims, checkpoint/history, and user workspace data.
3. Switched to `Old curation` and verified the original three workspace-owned targets were restored.
4. Switched back to `New curation` and verified the distinct new state was restored.

All seven global sentinels remained byte-identical after creation and both switches: settings, job, manifest, prepared download, source metadata, staging output, and completed-export metadata.

## Safety checkpoint

The real checkpoint path `/home/ubuntu/harsha/datasets/.dataset_studio/checkpoint.json` was absent both before and after all work. No workspace creation, switching, or registry GET was run against the user's real `.dataset_studio`.

## Remaining risk

Production-scale concurrent workspace changes were not exercised. The full suite covers locking and injected rollback failures, but this task did not run competing processes against a production-sized state tree.
