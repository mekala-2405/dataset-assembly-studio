# Named Curation Workspaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add recoverable named curation workspaces that can be saved, reset, and switched from the webpage while global settings and export data remain untouched.

**Architecture:** A focused backend module snapshots only `claims.json`, `dataset_checkpoints.json`, and `workspaces/` into named directories and maintains a small registry. FastAPI routes apply active-export guards and expose create/switch operations. The vanilla frontend adds a workspace selector and two confirmation dialogs, clears pending autosaves before state changes, and reloads after success.

**Tech Stack:** Python 3.10, FastAPI, Pydantic, `fcntl`, `pathlib`, `shutil`, vanilla HTML/CSS/JavaScript, `unittest`, headless Chrome.

## Global Constraints

- Workspace operations never modify project settings, export jobs/manifests, prepared archives, source datasets, staging directories, or completed exports.
- Workspace display names are trimmed, non-empty, and unique case-insensitively.
- New-workspace confirmation is exactly `START NEW WORKSPACE`.
- Switch confirmation is exactly `SWITCH WORKSPACE`.
- Creation and switching are blocked during queued/running/cancelling exports and preparing archives.
- Existing curation state is registered without being rewritten when the feature first loads.
- Failed snapshots or restores leave the active workspace usable and preserve recovery copies.
- Browser-local editor identity resets to `operator` after a successful create or switch.
- The application remains trusted-local and adds no authentication.
- This directory is not a Git repository, so each task ends with a test/review gate instead of a commit.

---

### Task 1: Snapshot and registry service

**Files:**
- Create: `dataset_studio/backend/named_workspaces.py`
- Create: `dataset_studio/tests/test_named_workspaces.py`

**Interfaces:**
- Produces: `ensure_workspace_registry(root: Path) -> dict`
- Produces: `create_named_workspace(root: Path, current_name: str, new_name: str, confirmation: str) -> dict`
- Produces: `switch_named_workspace(root: Path, workspace_id: str, confirmation: str) -> dict`
- Registry JSON contains `active_workspace_id` and `workspaces`, where each workspace has `id`, `name`, `created_at`, and `updated_at`.

- [ ] **Step 1: Write failing registration and create tests**

Create fixtures for all three active state targets plus global `settings.json`,
`jobs/`, and `downloads/`. Assert:

```python
registry = ensure_workspace_registry(root)
self.assertEqual(len(registry["workspaces"]), 1)
self.assertEqual(Path(root / ".dataset_studio" / "claims.json").read_text(), original_claims)

created = create_named_workspace(
    root,
    current_name="Development tests",
    new_name="Production curation",
    confirmation="START NEW WORKSPACE",
)
self.assertEqual(created["active_workspace"]["name"], "Production curation")
self.assertEqual(load_claims(root), {"claims": {}})
self.assertEqual(load_shared_checkpoints(root), {"checkpoints": {}, "history": {}})
self.assertTrue(
    root / ".dataset_studio" / "saved_workspaces"
    / created["previous_workspace"]["id"] / "claims.json"
)
```

Also assert byte-for-byte preservation of `settings.json`, a job file, and a
prepared archive.

- [ ] **Step 2: Run the new suite and verify RED**

Run:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_named_workspaces -v
```

Expected: import failure because `backend.named_workspaces` does not exist.

- [ ] **Step 3: Implement registration, validation, and safe snapshots**

Use explicit active targets:

```python
ACTIVE_TARGETS = ("claims.json", "dataset_checkpoints.json", "workspaces")
NEW_CONFIRMATION = "START NEW WORKSPACE"
SWITCH_CONFIRMATION = "SWITCH WORKSPACE"
```

`ensure_workspace_registry` creates one `Current workspace` registry entry
only when the registry is missing and does not touch active state. Protect
registry/snapshot operations with an exclusive `fcntl.flock` on
`.dataset_studio/workspace_registry.lock`.

Snapshot into `.dataset_studio/saved_workspaces/.tmp-<uuid>`, write
`workspace.json`, verify every copied JSON file can be decoded, then rename it
to the workspace ID. When replacing an older snapshot, rename the older
directory to `.recovery-<workspace-id>-<timestamp>` first; restore it if the
final rename fails.

- [ ] **Step 4: Run registration/create tests and verify GREEN**

Use the Task 1 command. Expected: registration/create tests pass and global
files remain unchanged.

- [ ] **Step 5: Write failing switch, validation, and recovery tests**

Cover:

- wrong confirmation phrases;
- blank, slash-containing, and case-insensitive duplicate names;
- unknown workspace IDs;
- create → modify new active state → switch to old → switch back;
- failed snapshot copy using `unittest.mock.patch("shutil.copytree", side_effect=OSError("disk full"))`;
- registry and active state remain unchanged after the injected failure.

Assert restored user files, claims, shared checkpoint/history content, and
workspace names in both directions.

- [ ] **Step 6: Run Task 1 tests and verify the new cases are RED**

Use the Task 1 command. Expected: missing switch/recovery behavior failures.

- [ ] **Step 7: Implement clean activation and rollback**

Before switching, snapshot the current active state. Materialize the selected
snapshot into `.dataset_studio/.restore-<uuid>`, validate JSON, move current
active targets to `.dataset_studio/.rollback-<uuid>`, then move the staged
targets into place. If any move fails, remove only newly installed targets and
move every rollback target back. Update the registry only after activation
succeeds.

For a new workspace, snapshot and rename the current workspace, create a new
registry entry, then activate canonical empty values:

```json
{"claims": {}}
```

and:

```json
{"checkpoints": {}, "history": {}}
```

with an empty `workspaces/` directory.

- [ ] **Step 8: Run Task 1 suite to GREEN**

Expected: all named workspace service tests pass.

---

### Task 2: Guarded FastAPI workspace routes

**Files:**
- Modify: `dataset_studio/backend/app.py`
- Modify: `dataset_studio/tests/test_app.py`

**Interfaces:**
- Consumes: Task 1 service functions.
- Produces: `GET /api/workspace-registry`
- Produces: `POST /api/workspaces/new`
- Produces: `POST /api/workspaces/switch`

- [ ] **Step 1: Write failing route tests**

Add Pydantic payload fixtures and assert:

```python
registry = client.get("/api/workspace-registry")
self.assertEqual(registry.status_code, 200)

created = client.post("/api/workspaces/new", json={
    "current_name": "Development tests",
    "new_name": "Production curation",
    "confirmation": "START NEW WORKSPACE",
})
self.assertEqual(created.status_code, 200)
self.assertEqual(created.json()["active_workspace"]["name"], "Production curation")
```

Assert HTTP 422 for invalid confirmation/name, HTTP 404 for an unknown switch
target, and that a round-trip switch restores checkpoints.

- [ ] **Step 2: Run the focused app tests and verify RED**

Run:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_app -v
```

Expected: all three new routes return 404.

- [ ] **Step 3: Implement payload models and route error mapping**

Add:

```python
class NewWorkspacePayload(BaseModel):
    current_name: str
    new_name: str
    confirmation: str


class SwitchWorkspacePayload(BaseModel):
    workspace_id: str
    confirmation: str
```

Map unknown IDs to 404, active-job conflicts to 409, and validation or
confirmation errors to 422.

- [ ] **Step 4: Write failing active-job guard tests**

Persist representative job JSON records before creating the app and test each
blocking state:

```python
{"status": "running", "archive_status": "not_requested"}
{"status": "completed", "archive_status": "preparing"}
```

Assert both create and switch return HTTP 409 and include the blocking job ID.
Assert completed/ready and failed jobs do not block.

- [ ] **Step 5: Run guard tests and verify RED**

Use the Task 2 command. Expected: route allows workspace changes despite an
active job.

- [ ] **Step 6: Add the job-state guard**

Before create/switch, inspect `export_jobs.list()` and reject when:

```python
job["status"] in {"queued", "running", "cancelling"}
or job.get("archive_status") == "preparing"
```

Do not modify or cancel the job.

- [ ] **Step 7: Run Task 1 and Task 2 suites to GREEN**

Run both focused commands. Expected: zero failures.

---

### Task 3: Workspace selector and destructive confirmation dialogs

**Files:**
- Modify: `dataset_studio/frontend/index.html`
- Modify: `dataset_studio/frontend/app.js`
- Modify: `dataset_studio/frontend/phases.css`
- Modify: `dataset_studio/tests/test_app.py`

**Interfaces:**
- Consumes: Task 2 routes.
- Adds DOM IDs: `workspace-name`, `workspace-select`, `switch-workspace`,
  `new-workspace`, `new-workspace-dialog`, and `switch-workspace-dialog`.

- [ ] **Step 1: Write failing static frontend checks**

Fetch `/` and `/static/app.js`. Assert the controls/dialog IDs exist and the
JavaScript contains:

```text
START NEW WORKSPACE
SWITCH WORKSPACE
loadWorkspaceRegistry
startNewWorkspace
switchWorkspace
localStorage.removeItem('dataset-studio-user')
```

Also assert warning copy includes `Settings and exports are preserved` and
`Users, claims, drafts, approvals, and checkpoint history will be replaced`.

- [ ] **Step 2: Run the focused static test and verify RED**

Use the Task 2 test command. Expected: missing IDs/functions/text.

- [ ] **Step 3: Add header controls and accessible dialogs**

Add a compact header workspace block with active name, selector, Switch button,
and `Save & start new…`. Use native `<dialog>` elements and labeled fields.
The new dialog contains current/new name fields and an exact-phrase input. The
switch dialog displays current/destination names and an exact-phrase input.
Both dialogs have Cancel buttons and warning panels listing reset/preserved
scope.

- [ ] **Step 4: Implement registry rendering and confirmation state**

Extend frontend state with `workspaceRegistry`. Call
`loadWorkspaceRegistry()` during initial loading. Disable actions until:

```javascript
currentName.trim()
&& newName.trim()
&& confirmation === 'START NEW WORKSPACE'
```

and:

```javascript
selectedWorkspaceId !== activeWorkspaceId
&& confirmation === 'SWITCH WORKSPACE'
```

Show API failures inside the dialog without closing it.

- [ ] **Step 5: Implement safe transition requests**

Before either POST:

```javascript
clearTimeout(state.saveTimer);
const current = state.catalog.find((item) => item.path === state.currentDataset);
if (current && state.dirty) {
  const saved = await persistCheckpoint(current, 'draft');
  if (!saved) return;
}
```

After success:

```javascript
localStorage.removeItem('dataset-studio-user');
setSaveStatus('Workspace saved. Loading the new workspace…', 'saved');
window.setTimeout(() => window.location.reload(), 500);
```

- [ ] **Step 6: Style responsive warning/dialog states**

Keep dialogs within `min(620px, calc(100vw - 32px))`, make warning scope
visually distinct, prevent action overlap at 390 pixels, and use existing
paper/leaf/red variables. Do not alter the phase workflow.

- [ ] **Step 7: Run the app suite to GREEN**

Expected: route and static frontend tests pass.

---

### Task 4: Documentation and complete verification

**Files:**
- Modify: `dataset_studio/README.md`
- Modify: `docs/superpowers/plans/2026-07-27-named-curation-workspaces.md`

**Interfaces:**
- Consumes: all prior tasks.

- [x] **Step 1: Document workspace behavior and recovery**

Add a README section explaining:

- workspace-owned versus global state;
- create and switch confirmations;
- active-job blocking;
- saved snapshot path;
- browser editor reset;
- manual recovery from `.recovery-*` directories.

- [x] **Step 2: Run the full test suite**

Run:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest discover -s dataset_studio/tests -v
```

Expected: all tests pass with zero failures.

- [x] **Step 3: Run rendered desktop and mobile QA**

Browser plugin availability must be checked first. If absent, use the installed
headless Chrome fallback without adding dependencies. At 1440×1000 and
emulated 390×844:

1. verify page identity and non-blank content;
2. open the new-workspace dialog;
3. verify warning text and initially disabled action;
4. enter names and an incorrect phrase and keep the action disabled;
5. enter `START NEW WORKSPACE` and enable the action;
6. cancel without changing real workspace state;
7. open the switch dialog and verify destination naming;
8. confirm no relevant console errors or horizontal document overflow.

- [x] **Step 4: Execute a temporary-root end-to-end state round trip**

Against a temporary dataset root, create a named workspace, write distinct
checkpoint/user data in the new workspace, switch to the old workspace, then
switch back. Verify both states and all global sentinel files after each
transition. Do not run this mutation check against the user's real
`.dataset_studio`.

- [x] **Step 5: Mark plan complete from fresh evidence**

Check each plan item only after the corresponding command/output or rendered
interaction has been observed. Record any untested production-scale
concurrency risk rather than claiming it was exercised.
