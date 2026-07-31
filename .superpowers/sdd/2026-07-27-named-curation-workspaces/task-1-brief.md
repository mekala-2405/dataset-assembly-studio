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

