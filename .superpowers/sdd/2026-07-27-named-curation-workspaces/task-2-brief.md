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

