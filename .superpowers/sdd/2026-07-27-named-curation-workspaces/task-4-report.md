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


## Fix Round 1: corrected safety and browser evidence

This section supersedes the earlier incorrect checkpoint-path statement. The monitored real file was `/home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json`, not `checkpoint.json`. Every phase captured SHA-256 and the nanosecond-resolved `stat` mtime before and after. All Python processes that could import `backend.app` started after `cd` into a freshly created temporary directory, with `PYTHONPATH=/home/ubuntu/harsha/datasets/dataset_studio`.

### Actual checkpoint safety snapshots

#### Full suite

Before:

```text
022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8  /home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
mtime_ns=2026-07-27 17:07:28.424493736 +0530 size=140502 path=/home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
```

After:

```text
022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8  /home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
mtime_ns=2026-07-27 17:07:28.424493736 +0530 size=140502 path=/home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
```

Byte-for-byte safety snapshot comparison: `FULL_SUITE_SAFETY_EQUAL=0`.

#### Temporary-root backend round trip

Before:

```text
022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8  /home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
mtime_ns=2026-07-27 17:07:28.424493736 +0530 size=140502 path=/home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
```

After:

```text
022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8  /home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
mtime_ns=2026-07-27 17:07:28.424493736 +0530 size=140502 path=/home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
```

Byte-for-byte safety snapshot comparison: `BACKEND_ROUNDTRIP_SAFETY_EQUAL=0`.

#### Rendered server/browser QA

Before:

```text
022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8  /home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
mtime_ns=2026-07-27 17:07:28.424493736 +0530 size=140502 path=/home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
```

After:

```text
022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8  /home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
mtime_ns=2026-07-27 17:07:28.424493736 +0530 size=140502 path=/home/ubuntu/harsha/datasets/.dataset_studio/dataset_checkpoints.json
```

Byte-for-byte safety snapshot comparison: `RENDERED_QA_SAFETY_EQUAL=0`.

The SHA-256 was the expected `022ed560ee6a8513aced79ab9737b4374db0c94e4267762828e472b258c8e4f8` in every snapshot. The mtime was unchanged at `2026-07-27 17:07:28.424493736 +0530`.

### Reproducible phase commands and results

Full suite (runner created with `mktemp -d`, then used as cwd):

```bash
cd "$runner"
PYTHONPATH=/home/ubuntu/harsha/datasets/dataset_studio \
  /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest discover \
  -s /home/ubuntu/harsha/datasets/dataset_studio/tests -v
```

Result: exit 0; `Ran 70 tests in 2.287s`; `OK`.

Backend round trip (a fresh `mktemp -d` runner cwd):

```bash
cd "$runner"
PYTHONPATH=/home/ubuntu/harsha/datasets/dataset_studio \
  /home/ubuntu/miniforge3/envs/lingbot/bin/python /tmp/task4_backend_roundtrip.py
```

Result JSON:

```json
{"global_sentinels": 7, "http_calls": 4, "new_workspace": "New curation", "old_workspace": "Old curation", "temporary_root": "created and removed", "transitions": ["create", "switch-old", "switch-new"]}
```

The FastAPI routes created a named workspace, wrote distinct claims/checkpoint-history/user data, switched old, then switched new; seven global sentinels remained byte-identical after every transition.

Rendered QA used a separate fresh temporary dataset root as both Uvicorn cwd and Chrome/CDP test target. Browser plugin was absent; Node, Playwright, and `package.json` were absent. The permitted fallback was `/usr/bin/google-chrome --headless=new --no-sandbox --password-store=basic` with CDP. The CDP Python harness ran from a different fresh temporary cwd; screenshots were saved under `/tmp`.

### Raw browser interaction result

The following is the exact JSON emitted by the browser harness. It records page title/URL/nonblank/overlay, desktop and mobile widths, confirmation states, registry bytes and parsed state before/after each Cancel, relevant `Runtime.exceptionThrown` and `Log.entryAdded` arrays, and the separately classified favicon entry.

```json
{"browser_plugin": "absent", "console_error_or_warning_relevant": [], "console_errors": 0, "desktop": {"identity": {"body": "Skip to workspace\n\nLOCAL LEROBOT WORKBENCH\n\nDataset Assembly Studio\n\nWorkspace\nBrowser destination\n\nChoose workspace\nBrowser origin\nBrowser destination\nSwitch\nSave & start new\u2026\nWorking as\nRelease all my claims\nRescan folder\nNo unsaved changes\n1 Sources\n2 Output set\n3 Cameras\n4 Joints\n5 Episodes\n6 Tasks\n7 Balance\n8 Preflight stale\n9 Export\n\nReview, normalize, and curate without touching a source dataset.\n\n0 datasets\n0 valid\n0 usable episodes\nFind a dataset\nSource catalog\n0 source folders \u00b7 0 recorded datasets\nAdd flag", "nonblank": true, "overlay": false, "scrollWidth": 1440, "title": "Dataset Assembly Studio", "url": "http://127.0.0.1:54045/", "width": 1440}, "new_dialog": {"cancelled_unchanged": true, "exact_phrase_enabled": true, "initial_disabled": true, "warning": true, "wrong_phrase_disabled": true}, "viewport": "1440x1000"}, "fallback": "headless Chrome CDP", "favicon_log_entries": [{"method": "Log.entryAdded", "params": {"entry": {"level": "error", "networkRequestId": "641396.20", "source": "network", "text": "Failed to load resource: the server responded with a status of 404 (Not Found)", "timestamp": 1785152558151.173, "url": "http://127.0.0.1:54045/favicon.ico"}}}], "ignored_browser_asset_entries": 1, "log_entry_added_relevant": [], "mobile": {"identity": {"body": "Skip to workspace\n\nLOCAL LEROBOT WORKBENCH\n\nDataset Assembly Studio\n\nWorkspace\nBrowser destination\n\nChoose workspace\nBrowser origin\nBrowser destination\nSwitch\nSave & start new\u2026\nWorking as\nRelease all my claims\nRescan folder\nNo unsaved changes\n1 Sources\n2 Output set\n3 Cameras\n4 Joints\n5 Episodes\n6 Tasks\n7 Balance\n8 Preflight stale\n9 Export\n\nReview, normalize, and curate without touching a source dataset.\n\n0 datasets\n0 valid\n0 usable episodes\nFind a dataset\nSource catalog\n0 source folders \u00b7 0 recorded datasets\nAdd flag", "nonblank": true, "overlay": false, "scrollWidth": 390, "title": "Dataset Assembly Studio", "url": "http://127.0.0.1:54045/", "width": 390}, "switch_dialog": {"cancelled_unchanged": true, "current": "Browser destination", "destination": "Browser origin", "exact_phrase_enabled": true, "initial_disabled": true, "wrong_phrase_disabled": true}, "viewport": "390x844 emulated"}, "registry": {"after_new_cancel_b64": "ewogICJhY3RpdmVfd29ya3NwYWNlX2lkIjogIjJlMDg2YzE3NzE5NjQ4MDY4NWVkMTE1NDkxYTkyZDFiIiwKICAid29ya3NwYWNlcyI6IFsKICAgIHsKICAgICAgImNyZWF0ZWRfYXQiOiAiMjAyNi0wNy0yN1QxMTo0MjozNi43NzQwNzgrMDA6MDAiLAogICAgICAiaWQiOiAiNTMyYWEyMWMxNjQxNDc4OGFjZGIyMmExYmQ4ZDExMTUiLAogICAgICAibmFtZSI6ICJCcm93c2VyIG9yaWdpbiIsCiAgICAgICJ1cGRhdGVkX2F0IjogIjIwMjYtMDctMjdUMTE6NDI6MzYuNzc1MjgxKzAwOjAwIgogICAgfSwKICAgIHsKICAgICAgImNyZWF0ZWRfYXQiOiAiMjAyNi0wNy0yN1QxMTo0MjozNi43NzYzODIrMDA6MDAiLAogICAgICAiaWQiOiAiMmUwODZjMTc3MTk2NDgwNjg1ZWQxMTU0OTFhOTJkMWIiLAogICAgICAibmFtZSI6ICJCcm93c2VyIGRlc3RpbmF0aW9uIiwKICAgICAgInVwZGF0ZWRfYXQiOiAiMjAyNi0wNy0yN1QxMTo0MjozNi43NzYzODIrMDA6MDAiCiAgICB9CiAgXQp9", "after_new_cancel_state": {"active_workspace_id": "2e086c177196480685ed115491a92d1b", "workspaces": [{"created_at": "2026-07-27T11:42:36.774078+00:00", "id": "532aa21c16414788acdb22a1bd8d1115", "name": "Browser origin", "updated_at": "2026-07-27T11:42:36.775281+00:00"}, {"created_at": "2026-07-27T11:42:36.776382+00:00", "id": "2e086c177196480685ed115491a92d1b", "name": "Browser destination", "updated_at": "2026-07-27T11:42:36.776382+00:00"}]}, "after_switch_cancel_b64": "ewogICJhY3RpdmVfd29ya3NwYWNlX2lkIjogIjJlMDg2YzE3NzE5NjQ4MDY4NWVkMTE1NDkxYTkyZDFiIiwKICAid29ya3NwYWNlcyI6IFsKICAgIHsKICAgICAgImNyZWF0ZWRfYXQiOiAiMjAyNi0wNy0yN1QxMTo0MjozNi43NzQwNzgrMDA6MDAiLAogICAgICAiaWQiOiAiNTMyYWEyMWMxNjQxNDc4OGFjZGIyMmExYmQ4ZDExMTUiLAogICAgICAibmFtZSI6ICJCcm93c2VyIG9yaWdpbiIsCiAgICAgICJ1cGRhdGVkX2F0IjogIjIwMjYtMDctMjdUMTE6NDI6MzYuNzc1MjgxKzAwOjAwIgogICAgfSwKICAgIHsKICAgICAgImNyZWF0ZWRfYXQiOiAiMjAyNi0wNy0yN1QxMTo0MjozNi43NzYzODIrMDA6MDAiLAogICAgICAiaWQiOiAiMmUwODZjMTc3MTk2NDgwNjg1ZWQxMTU0OTFhOTJkMWIiLAogICAgICAibmFtZSI6ICJCcm93c2VyIGRlc3RpbmF0aW9uIiwKICAgICAgInVwZGF0ZWRfYXQiOiAiMjAyNi0wNy0yN1QxMTo0MjozNi43NzYzODIrMDA6MDAiCiAgICB9CiAgXQp9", "after_switch_cancel_state": {"active_workspace_id": "2e086c177196480685ed115491a92d1b", "workspaces": [{"created_at": "2026-07-27T11:42:36.774078+00:00", "id": "532aa21c16414788acdb22a1bd8d1115", "name": "Browser origin", "updated_at": "2026-07-27T11:42:36.775281+00:00"}, {"created_at": "2026-07-27T11:42:36.776382+00:00", "id": "2e086c177196480685ed115491a92d1b", "name": "Browser destination", "updated_at": "2026-07-27T11:42:36.776382+00:00"}]}, "before_b64": "ewogICJhY3RpdmVfd29ya3NwYWNlX2lkIjogIjJlMDg2YzE3NzE5NjQ4MDY4NWVkMTE1NDkxYTkyZDFiIiwKICAid29ya3NwYWNlcyI6IFsKICAgIHsKICAgICAgImNyZWF0ZWRfYXQiOiAiMjAyNi0wNy0yN1QxMTo0MjozNi43NzQwNzgrMDA6MDAiLAogICAgICAiaWQiOiAiNTMyYWEyMWMxNjQxNDc4OGFjZGIyMmExYmQ4ZDExMTUiLAogICAgICAibmFtZSI6ICJCcm93c2VyIG9yaWdpbiIsCiAgICAgICJ1cGRhdGVkX2F0IjogIjIwMjYtMDctMjdUMTE6NDI6MzYuNzc1MjgxKzAwOjAwIgogICAgfSwKICAgIHsKICAgICAgImNyZWF0ZWRfYXQiOiAiMjAyNi0wNy0yN1QxMTo0MjozNi43NzYzODIrMDA6MDAiLAogICAgICAiaWQiOiAiMmUwODZjMTc3MTk2NDgwNjg1ZWQxMTU0OTFhOTJkMWIiLAogICAgICAibmFtZSI6ICJCcm93c2VyIGRlc3RpbmF0aW9uIiwKICAgICAgInVwZGF0ZWRfYXQiOiAiMjAyNi0wNy0yN1QxMTo0MjozNi43NzYzODIrMDA6MDAiCiAgICB9CiAgXQp9", "before_state": {"active_workspace_id": "2e086c177196480685ed115491a92d1b", "workspaces": [{"created_at": "2026-07-27T11:42:36.774078+00:00", "id": "532aa21c16414788acdb22a1bd8d1115", "name": "Browser origin", "updated_at": "2026-07-27T11:42:36.775281+00:00"}, {"created_at": "2026-07-27T11:42:36.776382+00:00", "id": "2e086c177196480685ed115491a92d1b", "name": "Browser destination", "updated_at": "2026-07-27T11:42:36.776382+00:00"}]}, "unchanged_after_new_cancel": true, "unchanged_after_switch_cancel": true}, "runtime_exception_thrown_relevant": [], "screenshots": ["/tmp/task-4-fix1-desktop-page.png", "/tmp/task-4-fix1-desktop-new-confirmed.png", "/tmp/task-4-fix1-mobile-switch-confirmed.png"], "url": "http://127.0.0.1:54045/"}
```

Screenshots:

- `/tmp/task-4-fix1-desktop-page.png`
- `/tmp/task-4-fix1-desktop-new-confirmed.png`
- `/tmp/task-4-fix1-mobile-switch-confirmed.png`

The only `Log.entryAdded` error was Chrome's automatic `GET /favicon.ico` 404, recorded above as `favicon_log_entries`; it is not a workspace runtime error. Relevant `Runtime.exceptionThrown`, `Log.entryAdded`, and console error/warning arrays were all empty.
