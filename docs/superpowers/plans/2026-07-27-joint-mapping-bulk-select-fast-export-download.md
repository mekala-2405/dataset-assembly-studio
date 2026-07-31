# Joint Mapping, Bulk Selection, Faster Export, and Lazy Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add automatic editable six-joint mapping, bulk usable-episode selection, two-camera parallel encoding, and on-demand `.tar.gz` downloads.

**Architecture:** A pure joint-contract module reads and validates feature metadata and supplies frozen mappings to the export planner and writer. Export jobs parallelize only the two camera encodes for one episode, preserving episode order and existing verification. A separate archive service creates cached `.tar.gz` files lazily for completed jobs and exposes them through guarded API routes.

**Tech Stack:** Python, FastAPI, PyArrow, PyAV, `concurrent.futures`, `tarfile`, vanilla HTML/CSS/JavaScript, `unittest`.

## Global Constraints

- Exported `action` and `observation.state` both use the six canonical `.pos` names in the approved order.
- Mapping reorders values only; it never converts units or synthesizes values.
- Seven-element end-effector actions remain incompatible.
- Select All includes only valid episodes of at least two seconds and preserves existing prompt edits.
- Video output remains H.264/yuv420p, 30 FPS, and 640×480.
- At most two camera transcodes run concurrently.
- Export never creates an archive unless download preparation is requested.
- Download format is `.tar.gz` only and contains one top-level dataset folder.
- Source datasets remain read-only.
- This workspace is not a Git repository, so task review boundaries replace commit steps.

---

### Task 1: Joint contract proposal and validation

**Files:**
- Create: `dataset_studio/backend/joint_mapping.py`
- Create: `dataset_studio/tests/test_joint_mapping.py`

**Interfaces:**
- Produces: `CANONICAL_JOINTS: tuple[str, ...]`
- Produces: `build_joint_contract(dataset_path: Path) -> JointContract`
- Produces: `validate_joint_mapping(mapping: dict, contract: JointContract) -> list[str]`
- Produces: `reorder_vectors(values: pyarrow.ChunkedArray, mapping: dict[str, int]) -> pyarrow.Array`
- `JointContract.to_dict()` returns JSON-safe `action_names`, `state_names`, shapes, proposal, compatibility, and errors.

- [ ] **Step 1: Write failing alias-proposal tests**

```python
def test_proposes_canonical_positions_for_standard_and_main_aliases():
    contract = contract_from_names(
        ["main_shoulder_pan", "main_shoulder_lift", "main_elbow_flex",
         "main_wrist_flex", "main_wrist_roll", "main_gripper"],
        ["shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos",
         "wrist_flex.pos", "wrist_roll.pos", "gripper.pos"],
    )
    assert contract.proposal["action"]["shoulder_pan.pos"] == 0
    assert contract.proposal["action"]["gripper.pos"] == 5
    assert contract.proposal["observation.state"]["wrist_roll.pos"] == 4
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_joint_mapping -v
```

Expected: import failure because `backend.joint_mapping` does not exist.

- [ ] **Step 3: Implement canonical aliases and metadata loading**

Implement:

```python
CANONICAL_JOINTS = (
    "shoulder_pan.pos", "shoulder_lift.pos", "elbow_flex.pos",
    "wrist_flex.pos", "wrist_roll.pos", "gripper.pos",
)

def normalize_joint_name(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if value.startswith("main_"):
        value = value[5:]
    if value.endswith("_pos"):
        value = value[:-4]
    return value
```

`build_joint_contract` reads `meta/info.json`, extracts `action` and
`observation.state` names/shapes, and proposes an index only when a normalized
source name uniquely matches a canonical name.

- [ ] **Step 4: Add failing mapping-validation and reorder tests**

Cover complete one-to-one mappings, duplicate indices, missing slots,
out-of-range indices, 7D actions, and:

```python
values = pa.chunked_array([pa.array([[10, 20, 30, 40, 50, 60]], type=pa.list_(pa.float32(), 6))])
mapping = {name: index for name, index in zip(CANONICAL_JOINTS, [5, 4, 3, 2, 1, 0])}
assert reorder_vectors(values, mapping).to_pylist() == [[60, 50, 40, 30, 20, 10]]
```

- [ ] **Step 5: Run tests and confirm the new assertions fail for missing behavior**

Use the Task 1 command and confirm validation/reordering failures.

- [ ] **Step 6: Implement strict validation and float32 reordering**

Validation requires both feature maps to have exactly the canonical keys and
each integer position `0..5` exactly once. `reorder_vectors` indexes each
source row using canonical key order and returns fixed-size float32 lists.

- [ ] **Step 7: Run Task 1 tests to GREEN**

Expected: all joint mapping tests pass.

---

### Task 2: Joint contract API, checkpoint approval, planner, and writer

**Files:**
- Modify: `dataset_studio/backend/app.py`
- Modify: `dataset_studio/backend/export_plan.py`
- Modify: `dataset_studio/backend/v21_writer.py`
- Modify: `dataset_studio/tests/test_app.py`
- Modify: `dataset_studio/tests/test_export_plan.py`
- Modify: `dataset_studio/tests/test_v21_writer.py`

**Interfaces:**
- Consumes: Task 1 `build_joint_contract`, `validate_joint_mapping`, `reorder_vectors`, and `CANONICAL_JOINTS`.
- Extends: `PlanEpisode.joint_mapping: dict[str, dict[str, int]]`
- Produces: `GET /api/datasets/joint-contract?dataset_path=...`

- [ ] **Step 1: Write failing API tests**

Assert a known six-position fixture returns a complete automatic proposal and
an unknown path returns 404. Add an approval test where:

```python
payload["status"] = "approved"
payload["recipe"]["joint_mapping"] = {}
response = client.post("/api/checkpoints", json=payload)
self.assertEqual(response.status_code, 422)
```

Draft autosaves remain allowed with incomplete mappings.

- [ ] **Step 2: Run API tests to confirm RED**

Run:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_app -v
```

Expected: joint-contract route is 404 and incomplete approval is accepted.

- [ ] **Step 3: Add the route and approval guard**

Resolve `dataset_path` only from the cached catalog. For approved checkpoints,
build its contract and reject non-empty validation errors with HTTP 422. Draft
and excluded checkpoints preserve current behavior.

- [ ] **Step 4: Write failing planner tests**

Add approved recipes with complete, missing, duplicate, and 7D mappings.
Assert complete mappings are frozen into `PlanEpisode`, while all incompatible
cases produce `category == "joints"` and `phase == "joints"`.

- [ ] **Step 5: Run planner tests to confirm RED**

Run:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_export_plan -v
```

- [ ] **Step 6: Extend planner contracts and validation**

Add:

```python
@dataclass(frozen=True)
class PlanEpisode:
    # existing fields...
    joint_mapping: dict[str, dict[str, int]]
```

Build one joint contract per dataset, validate the recipe mapping, add grouped
blocking errors, and copy a deep immutable mapping into each retained episode.
Replace direct source-name equality as the compatibility gate with canonical
post-mapping shapes/names; dtype and six-position length remain strict.

- [ ] **Step 7: Write failing writer reorder tests**

Create source action/state rows in reversed order and pass distinct complete
mappings. Assert the output values follow `CANONICAL_JOINTS` and generated
`info.json` gives both features the canonical names.

- [ ] **Step 8: Run writer tests to confirm RED**

Run:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_v21_writer -v
```

- [ ] **Step 9: Apply mapping in `write_episode_data`**

Call `reorder_vectors` separately for action and state. Make
`finalize_metadata` always use shape `[6]` and `list(CANONICAL_JOINTS)` for both
features. Add both mappings to provenance.

- [ ] **Step 10: Run all Task 2 suites to GREEN**

Run the three focused commands and confirm zero failures.

---

### Task 3: Joint Mapping phase and bulk episode selection UI

**Files:**
- Modify: `dataset_studio/frontend/index.html`
- Modify: `dataset_studio/frontend/app.js`
- Modify: `dataset_studio/frontend/phases.css`

**Interfaces:**
- Consumes: `GET /api/datasets/joint-contract`
- Saves: `recipe.joint_mapping.action` and
  `recipe.joint_mapping["observation.state"]`

- [ ] **Step 1: Add static failing selector checks**

Extend `test_app.py` to fetch `/` and `/static/app.js`, asserting the HTML
contains `id="joints"`, `id="select-all-episodes"`, and
`id="clear-episodes"`, and JavaScript contains `renderJointMapping`,
`selectAllUsableEpisodes`, and `clearEpisodeSelection`.

- [ ] **Step 2: Run the selector test to confirm RED**

Use the Task 2 API command. Expected: missing IDs/functions.

- [ ] **Step 3: Add phase structure**

Insert **4 Joint Mapping** after Cameras and renumber Episodes through Export.
Add a joint contract summary, compatibility notice, and a six-row mapping table
with canonical joint, action source selector, and state source selector.

- [ ] **Step 4: Implement hydration and automatic proposal**

On first rendering for an open dataset:

1. fetch its joint contract;
2. use saved recipe mapping when present;
3. otherwise copy the automatic proposal into local state;
4. render six canonical rows;
5. schedule one autosave after proposal hydration;
6. autosave and mark preflight stale on every manual selector change.

Add `joint_mapping` to `recipeForDataset` and `hydrateDataset`.

- [ ] **Step 5: Implement bulk episode controls**

`selectAllUsableEpisodes` loops the current dataset once, skips
`episode.exclusion_reason`, calls the existing choice construction logic only
for missing keys, renders once, and schedules one autosave. Existing choices
and edited prompts remain unchanged. `clearEpisodeSelection` deletes only keys
belonging to the current dataset, renders once, and autosaves once.

- [ ] **Step 6: Run static/API tests to GREEN**

Expected: selectors and named functions are present and backend tests pass.

- [ ] **Step 7: Perform rendered interaction QA**

Serve the app, use Chrome CDP, open a dataset, navigate Cameras → Joint
Mapping → Episodes, verify auto-filled selectors, click Select All, and assert:

```javascript
document.querySelectorAll('.episode-tile.selected').length > 1
```

Then click Clear Selection and assert the selected count is zero. Capture
desktop and 390px screenshots and confirm no runtime errors or horizontal
overflow.

---

### Task 4: Two-camera parallel video export

**Files:**
- Modify: `dataset_studio/backend/video_export.py`
- Modify: `dataset_studio/backend/jobs.py`
- Modify: `dataset_studio/tests/test_video_export.py`
- Modify: `dataset_studio/tests/test_jobs_export.py`

**Interfaces:**
- Extends: `normalize_episode_video(..., preset="veryfast", crf=20)`
- Produces: `normalize_episode_cameras(episode, staging, plan, cancel, progress) -> list[VideoExportResult]`

- [ ] **Step 1: Write failing encoder-option test**

Normalize a synthetic clip with default options and inspect the returned result
plus decodable output. Add an injected/monkey-patched stream factory only if
PyAV does not expose preset metadata; otherwise assert output properties and
the function signature defaults.

- [ ] **Step 2: Run video tests to confirm RED**

Expected: current defaults do not accept `preset` and `crf`.

- [ ] **Step 3: Add explicit encoder options**

Validate non-empty preset and integer CRF `0..51`, then set:

```python
output_stream.options = {"preset": preset, "crf": str(crf)}
```

with defaults `veryfast` and `20`.

- [ ] **Step 4: Write failing concurrency test**

Inject a camera normalizer that increments a locked active counter, waits on a
barrier shared by two calls, and records `max_active`. Assert
`max_active == 2`, both results return, and cancellation causes the episode
export to raise without starting metadata finalization.

- [ ] **Step 5: Run jobs tests to confirm RED**

Use:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest dataset_studio.tests.test_jobs_export -v
```

- [ ] **Step 6: Implement bounded camera concurrency**

Create a `ThreadPoolExecutor(max_workers=2)` per episode, submit exactly the two
camera calls, collect both futures, cancel pending work on error/cancellation,
and re-raise the first failure. Each task receives its own source and
destination. Update job fields:

```json
{
  "current_stage": "videos",
  "completed_cameras": 1,
  "total_cameras": 2
}
```

Set stages around Parquet writing, metadata, and verification.

- [ ] **Step 7: Run Task 4 tests and end-to-end export test to GREEN**

Confirm synthetic output still passes the existing final verifier.

- [ ] **Step 8: Record a before/after benchmark**

Export the same short synthetic fixture sequentially and through the new
two-camera helper. Record elapsed times in test/QA notes without asserting a
fragile wall-clock threshold. Confirm both outputs have equal verified frame
counts.

---

### Task 5: Lazy persisted `.tar.gz` preparation and download API

**Files:**
- Create: `dataset_studio/backend/archives.py`
- Create: `dataset_studio/tests/test_archives.py`
- Modify: `dataset_studio/backend/jobs.py`
- Modify: `dataset_studio/backend/app.py`
- Modify: `dataset_studio/tests/test_app.py`

**Interfaces:**
- Produces: `create_export_archive(source: Path, destination: Path, cancel=None) -> Path`
- Extends: `ExportJobManager.prepare_archive(job_id: str) -> dict`
- Produces: `ExportJobManager.download_path(job_id: str) -> Path`
- Produces: `POST /api/export/jobs/{job_id}/archive`
- Produces: `GET /api/export/jobs/{job_id}/download`

- [ ] **Step 1: Write failing archive structure tests**

Create a completed output fixture and assert the generated archive:

```python
with tarfile.open(archive, "r:gz") as handle:
    names = handle.getnames()
self.assertTrue(all(name == "combined" or name.startswith("combined/") for name in names))
```

Also assert temporary-file atomic replacement and source absence errors.

- [ ] **Step 2: Run archive tests to confirm RED**

Expected: `backend.archives` import failure.

- [ ] **Step 3: Implement safe atomic archive creation**

Use `tarfile.open(temp_path, "w:gz")`, add the source with
`arcname=source.name`, close it, and `os.replace(temp_path, destination)`.
Remove a failed temporary file. Do not delete or modify source output.

- [ ] **Step 4: Write failing manager lifecycle tests**

Assert:

- non-completed jobs are rejected;
- first request changes `archive_status` to `preparing`;
- completion changes it to `ready`;
- repeated preparation reuses an existing archive;
- missing output changes status to `failed`;
- `download_path` rejects non-ready and path-mismatched archives.

- [ ] **Step 5: Run lifecycle tests to confirm RED**

Use the focused jobs and archives commands.

- [ ] **Step 6: Add archive state to persisted jobs**

New jobs start with:

```json
{
  "archive_status": "not_requested",
  "archive_path": null,
  "archive_error": null
}
```

`prepare_archive` starts one daemon thread per job, writes under
`.dataset_studio/downloads/<job-id>.tar.gz`, and persists transitions under the
existing lock. On restart, `preparing` becomes `failed` with an interruption
message. Archive status never changes the completed export status.

- [ ] **Step 7: Write and implement API tests**

The POST route returns current job state. The GET route uses `FileResponse`
with media type `application/gzip` and filename
`<output-folder-name>.tar.gz`. Assert 409 before ready, 404 for unknown jobs,
and 200 with gzip bytes when ready.

- [ ] **Step 8: Run Task 5 suites to GREEN**

Expected: archive, jobs, and app tests pass.

---

### Task 6: Export download UI, documentation, and complete verification

**Files:**
- Modify: `dataset_studio/frontend/app.js`
- Modify: `dataset_studio/frontend/phases.css`
- Modify: `dataset_studio/README.md`
- Modify: `docs/superpowers/plans/2026-07-27-joint-mapping-bulk-select-fast-export-download.md`

**Interfaces:**
- Consumes: Task 5 archive POST/GET routes and archive job fields.

- [ ] **Step 1: Add failing static download-control check**

Assert `app.js` contains `prepareArchive` and renders both
`Prepare .tar.gz` and `Download .tar.gz`.

- [ ] **Step 2: Run static test to confirm RED**

Use the app test command.

- [ ] **Step 3: Render archive lifecycle controls**

For completed jobs:

- `not_requested`: button calls archive POST;
- `preparing`: disabled button and archive progress message;
- `ready`: anchor points to the download GET route with `download`;
- `failed`: show error plus a retry button.

Job polling continues while any archive is `preparing`, even when no export is
active.

- [ ] **Step 4: Update documentation**

Document the Joint Mapping phase, alias auto-mapping, manual correction,
Select/Clear All behavior, 7D incompatibility, two-camera CPU usage, lazy
archive creation, cached archive location, and disk duplication only after
download preparation.

- [ ] **Step 5: Run the complete test suite**

Run:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest discover -s dataset_studio/tests -v
```

Expected: all tests pass with zero failures.

- [ ] **Step 6: Run final rendered QA**

At desktop and 390px:

1. verify phase order and no overlap;
2. inspect automatic joint mappings;
3. manually change and restore one mapping and observe autosave;
4. Select All and Clear Selection;
5. inspect concurrent camera progress on an export fixture;
6. prepare an archive only after completion;
7. download and list the `.tar.gz`;
8. check Chrome runtime errors and document scroll width.

- [ ] **Step 7: Mark this plan complete only after fresh evidence**

Check every plan checkbox against test output and rendered evidence. Do not
claim completion from implementation inspection alone.
