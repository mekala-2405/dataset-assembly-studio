# Task 1: Snapshot and registry service report

## Implementation summary

Created `dataset_studio/backend/named_workspaces.py` with:

- `ensure_workspace_registry(root: Path) -> dict`, which creates one `Current workspace` only when the registry is absent and leaves all active state untouched.
- `create_named_workspace(root, current_name, new_name, confirmation) -> dict`, with exact confirmation text, blank/slash/case-insensitive duplicate-name validation, a validated active-state snapshot, and canonical empty active state.
- `switch_named_workspace(root, workspace_id, confirmation) -> dict`, with exact confirmation text, unknown-ID handling, current-state snapshots, staged restore validation, rollback, and registry updates after successful activation.
- The required exact constants: `ACTIVE_TARGETS = ("claims.json", "dataset_checkpoints.json", "workspaces")`, `NEW_CONFIRMATION = "START NEW WORKSPACE"`, and `SWITCH_CONFIRMATION = "SWITCH WORKSPACE"`.
- Exclusive `fcntl.flock` locking through `.dataset_studio/workspace_registry.lock` for all registry and snapshot operations.
- Temporary snapshot, restore, rollback, and snapshot-recovery directories; copied JSON files are decoded before snapshots/restores are activated.

Created `dataset_studio/tests/test_named_workspaces.py`. Every test creates its root with `tempfile.TemporaryDirectory`; no test targets the real `/home/ubuntu/harsha/datasets/.dataset_studio` directory.

## Tests and exact final results

Command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces -v
```

Output:

```text
test_create_validates_confirmation_and_workspace_names (dataset_studio.tests.test_named_workspaces.NamedWorkspaceTests)
Would fail if unsafe, duplicate, or unconfirmed requests could change workspace state. ... ok
test_failed_snapshot_copy_leaves_registry_and_active_state_unchanged (dataset_studio.tests.test_named_workspaces.NamedWorkspaceTests)
Would fail if a disk-full snapshot error partially renamed state or the registry. ... ok
test_registering_and_creating_workspace_snapshots_active_state_only (dataset_studio.tests.test_named_workspaces.NamedWorkspaceTests)
Would fail if registration modifies state or creation omits an active target. ... ok
test_switch_restores_each_workspace_active_state_in_both_directions (dataset_studio.tests.test_named_workspaces.NamedWorkspaceTests)
Would fail if switching lost claims, checkpoint history, or per-user workspace files. ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.020s

OK
```

## TDD RED and GREEN evidence

### Registration and create cycle

RED command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces -v
```

RED output:

```text
ModuleNotFoundError: No module named 'backend.named_workspaces'

Ran 1 test in 0.000s

FAILED (errors=1)
```

GREEN command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces -v
```

GREEN output:

```text
test_registering_and_creating_workspace_snapshots_active_state_only (...) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.004s

OK
```

### Switch, validation, and recovery cycle

RED command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces -v
```

RED output:

```text
ImportError: cannot import name 'switch_named_workspace' from 'backend.named_workspaces'

Ran 1 test in 0.000s

FAILED (errors=1)
```

GREEN command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces -v
```

GREEN output:

```text
Ran 4 tests in 0.021s

OK
```

### Self-review regression cycle

Self-review identified that `current_name` in a later create operation had syntax validation only, so it could duplicate a different existing workspace. A test reproduced it before the fix.

RED command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces.NamedWorkspaceTests.test_create_validates_confirmation_and_workspace_names -v
```

RED output:

```text
AssertionError: ValueError not raised

Ran 1 test in 0.007s

FAILED (failures=1)
```

GREEN command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces.NamedWorkspaceTests.test_create_validates_confirmation_and_workspace_names -v
```

GREEN output:

```text
Ran 1 test in 0.005s

OK
```

## Files changed

- `dataset_studio/backend/named_workspaces.py` (created)
- `dataset_studio/tests/test_named_workspaces.py` (created)
- `.superpowers/sdd/2026-07-27-named-curation-workspaces/task-1-report.md` (created)

## Self-review findings

- Fixed: `current_name` now uses the same case-insensitive duplicate validation as `new_name`, while excluding only the currently active registry entry.
- Confirmed: snapshots contain only the three explicit active targets; settings, jobs, and prepared downloads remain byte-for-byte unchanged in the registration/create test.
- Confirmed: the injected `shutil.copytree(..., side_effect=OSError("disk full"))` failure leaves the registry and active targets unchanged.
- Confirmed: switching in both directions restores claims, shared checkpoint/history content, user workspace files, and the expected registry names.
- Confirmed: snapshot replacement moves an existing snapshot to a recovery directory before final replacement and restores it if the final rename fails.

## Concerns

None for Task 1. The requested focused suite passes. No Git repository operations, commits, or mutations of the real studio state were performed.

## Fix Round 1

### Implementation summary

- Replaced direct registry `write_text` persistence with a unique staged file, `flush()`, `os.fsync()`, and atomic `os.replace()`.
- Made activation a retained transaction: `.restore-*` and `.rollback-*` are cleaned only after registry persistence succeeds.
- On activation or registry-write failure, newly installed targets are removed and all moved rollback targets are restored. Each rollback move is retried once; if moving remains unavailable, the target is copied back so the active state remains usable and the `.rollback-*` recovery copy is retained.
- Expanded global-preservation sentinels to include an export manifest, source dataset, staging directory, and completed export.

### Covering tests and TDD evidence

RED command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces -v
```

RED output:

```text
test_failed_activation_and_transient_rollback_restore_preserve_active_state (...) ... FAIL
test_registry_atomic_replace_failure_restores_prior_active_state (...) ... FAIL

======================================================================
FAIL: test_failed_activation_and_transient_rollback_restore_preserve_active_state (...)
AssertionError: "target move failed" does not match "rollback move failed"

FAIL: test_registry_atomic_replace_failure_restores_prior_active_state (...)
AssertionError: OSError not raised

----------------------------------------------------------------------
Ran 6 tests in 0.037s

FAILED (failures=2)
```

GREEN command:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest dataset_studio.tests.test_named_workspaces -v
```

GREEN output:

```text
test_create_validates_confirmation_and_workspace_names (...) ... ok
test_failed_activation_and_transient_rollback_restore_preserve_active_state (...) ... ok
test_failed_snapshot_copy_leaves_registry_and_active_state_unchanged (...) ... ok
test_permanent_rollback_move_failure_keeps_recovery_copy_and_active_state (...) ... ok
test_registering_and_creating_workspace_snapshots_active_state_only (...) ... ok
test_registry_atomic_replace_failure_restores_prior_active_state (...) ... ok
test_switch_restores_each_workspace_active_state_in_both_directions (...) ... ok

----------------------------------------------------------------------
Ran 7 tests in 0.058s

OK
```

The new coverage injects:

- an active-target installation failure plus a transient rollback restore failure;
- a persistent rollback move failure, asserting restored active state and retained `.rollback-*` recovery data;
- an atomic registry-replace failure, asserting the prior registry bytes and active targets are restored.

### Files changed

- `dataset_studio/backend/named_workspaces.py`
- `dataset_studio/tests/test_named_workspaces.py`
- `.superpowers/sdd/2026-07-27-named-curation-workspaces/task-1-report.md`

### Self-review

- Verified that the original activation error remains the reported failure even when rollback itself encounters an error.
- Verified that a successful retry removes temporary activation directories, while the copy fallback preserves rollback data for manual recovery.
- Verified that failed atomic registry replacement rolls back active targets before the function returns and leaves the previous registry bytes intact.
- Verified all mutation tests continue to use `TemporaryDirectory`; the real `.dataset_studio` state was not touched.

### Concerns

None. The focused Task 1 suite passes with the additional recovery and preservation coverage.
