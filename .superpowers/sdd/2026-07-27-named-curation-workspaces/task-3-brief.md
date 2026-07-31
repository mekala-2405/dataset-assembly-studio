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

