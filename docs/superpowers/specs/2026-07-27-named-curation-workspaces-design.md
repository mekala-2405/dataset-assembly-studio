# Named Curation Workspaces Design

## Goal

Let a local operator save the current curation state, start a clean named
workspace, and later switch between saved workspaces from the webpage without
deleting source datasets or duplicating export data.

## Scope

Each named workspace owns:

- local user profiles;
- dataset claims;
- draft, approved, and excluded checkpoints;
- append-only checkpoint history;
- flags, camera mappings, joint mappings, episode selections, and edited task
  prompts stored in those checkpoints.

The following remain global and are never copied or reset by workspace
operations:

- project/output settings;
- export job records and manifests;
- prepared download archives;
- source datasets;
- staging directories and completed exported datasets.

## Storage

The active workspace continues using the existing paths so current data access
code remains compatible:

```text
.dataset_studio/
├── claims.json
├── dataset_checkpoints.json
└── workspaces/
```

Named snapshots are stored beneath:

```text
.dataset_studio/saved_workspaces/<workspace-id>/
├── claims.json
├── dataset_checkpoints.json
├── workspaces/
└── workspace.json
```

`.dataset_studio/workspace_registry.json` stores the active workspace ID/name
and the available workspace metadata. IDs are generated independently of
display names. Display names must be non-empty, trimmed, and unique
case-insensitively.

When the feature first runs, existing active state is registered as the
initial workspace without changing its contents.

## Operations

### Save and start a new workspace

The UI asks for:

1. a name for the current workspace;
2. a name for the new workspace;
3. the exact confirmation phrase `START NEW WORKSPACE`.

The backend validates the request, copies the current active state into its
named snapshot, verifies the snapshot, clears only the three active
workspace-state targets, creates the new registry entry, and marks it active.
If snapshot creation fails, active state remains untouched.

### Switch workspace

The selector shows every named workspace and marks the active one. Switching
requires a warning confirmation because it replaces the visible curation
state. The backend:

1. snapshots the current active workspace;
2. verifies the selected snapshot;
3. restores the selected snapshot into temporary active paths;
4. atomically replaces each active state target;
5. updates the active workspace metadata.

The UI clears pending autosave timers before either operation and reloads only
after success. The browser's remembered editor name is reset to `operator`
when a new workspace starts or a different workspace is selected.

### Active-job guard

Creation and switching are rejected while an export is queued, running, or
cancelling, or while an archive is preparing. Settings and export state remain
global, but this guard avoids changing approvals while a background operation
is consuming a frozen project state.

## Recovery and Failure Handling

- Workspace state is copied to temporary directories and renamed only after
  successful serialization/copying.
- No source dataset, export folder, job record, settings file, or prepared
  archive is moved or deleted.
- A failed save or restore leaves the current active state and active registry
  entry unchanged.
- The API reports validation and conflict errors without reloading the page.
- Saved snapshots remain visible on disk for manual recovery.

## Web Interface

Add a `Workspace` control in the header with:

- the active workspace name;
- a selector for saved workspaces;
- `Switch` and `Save & start new…` buttons.

The creation dialog presents a red warning panel listing what will reset and
what will remain. Its action button stays disabled until both names are valid
and the exact confirmation phrase matches. The switching dialog names both
the current and destination workspace and requires an explicit confirmation.
Success is shown in the existing saved-status banner before the page reloads.

The application remains trusted-local software with no authentication. These
confirmations prevent accidental changes; they are not security controls.

## API

- `GET /api/workspace-registry`
- `POST /api/workspaces/new`
- `POST /api/workspaces/switch`

Create payload:

```json
{
  "current_name": "Development tests",
  "new_name": "Production curation",
  "confirmation": "START NEW WORKSPACE"
}
```

Switch payload:

```json
{
  "workspace_id": "opaque-id",
  "confirmation": "SWITCH WORKSPACE"
}
```

## Testing

Backend tests cover initial registration, unique names, snapshot contents,
clean new state, switching in both directions, preservation of global files,
incorrect confirmations, missing workspaces, snapshot failure safety, and the
active-job guard.

Static frontend tests cover the workspace controls, warning text, exact
confirmation phrases, and browser-local user reset. Rendered QA covers desktop
and 390-pixel layouts, dialog visibility, disabled/enabled confirmation
actions, selector switching, and browser console health.
