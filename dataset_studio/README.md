# Dataset Assembly Studio

Dataset Assembly Studio is a local web application for reviewing SO-101 LeRobot
datasets, selecting and editing episodes one dataset at a time, balancing the
combined selection, and exporting the approved work as one verified LeRobot
v2.1 dataset.

Source datasets are never modified. Drafts, approvals, claims, settings, export
manifests, downloads, and job state are stored beneath `.dataset_studio/`.

## Features

- Recursively discovers LeRobot datasets beneath the folder where the server is
  started.
- Rejects invalid Parquet, missing metadata, single-camera sources, and episodes
  shorter than two seconds before they can enter an export.
- Curates one dataset at a time with claims and per-action autosave.
- Previews representative camera views before mapping them to `wrist`,
  `front`, `top`, or another selected canonical second camera.
- Automatically maps six SO-101 positions for both `action` and
  `observation.state`, with manual corrections when needed.
- Shows an episode gallery with direct include checkboxes, task descriptions,
  thumbnails, all-camera video preview, Previous/Next navigation, Select all,
  flags, and editable final prompts.
- Groups the open dataset's source prompts with the same deterministic local
  embedding used by Global Balance, then selects an exact episode count for
  each subtask variant.
- Stores immutable approved checkpoint revisions without rewriting source data.
- Supports multiple trusted local editor profiles and separate named curation
  workspaces without requiring authentication.
- Balances by exact edited prompt and by local embedding-based task groups.
- Optionally asks Groq to suggest task-group names without changing prompts.
- Caps episodes per prompt and per task group with deterministic selection.
- Runs a blocking preflight for camera, joint, schema, media, duration, prompt,
  destination, and checkpoint compatibility.
- Exports normalized LeRobot v2.1 data with exactly two cameras, rebuilt
  indices, edited prompts, metadata, statistics, and provenance.
- Runs export in the background, supports cancellation, and prepares a
  downloadable `.tar.gz` only when requested.

## Requirements

- Linux. Workspace coordination uses `fcntl`, so Windows is not supported
  directly.
- Python 3.10 or newer.
- A modern browser.
- LeRobot datasets beneath one common dataset root.
- Enough free storage for the final dataset, export staging, and optionally a
  second full copy while preparing a `.tar.gz`.
- Two or more CPU cores are helpful because the two output camera streams are
  encoded concurrently.

The required Python packages are:

```text
fastapi
uvicorn
pydantic
pyarrow
av
numpy
httpx
pillow
python-dotenv
```

Groq is optional. Local clustering, group caps, and all other curation features
work without a Groq API key.

## Installation

### Option A: use the existing `lingbot` environment

This machine already has the required media and Parquet dependencies in the
`lingbot` Conda environment:

```bash
conda activate lingbot
cd /home/ubuntu/harsha/datasets
python -c "import av, fastapi, httpx, numpy, pyarrow, uvicorn; print('dependencies ready')"
```

If `conda activate` is unavailable in the current shell, the server can still
be started with the environment's absolute Python path shown in the Run
section.

### Option B: create a fresh virtual environment

Run these commands from the directory that contains `dataset_studio/`:

```bash
cd /home/ubuntu/harsha/datasets
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install fastapi "uvicorn[standard]" pydantic pyarrow av numpy httpx pillow python-dotenv
```

Verify the installation:

```bash
PYTHONPATH=dataset_studio python -c "from backend.app import app; print(app.title)"
```

Expected output:

```text
Dataset Assembly Studio
```

## Dataset folder preparation

Start the server from the common dataset root—not from inside
`dataset_studio/`. The current working directory becomes the dataset root.

Discovery is recursive. Every nested directory containing `meta/info.json` is
treated as a potential source dataset. Keep backups and unrelated LeRobot
copies outside this root if they should not appear in the Source catalog.

A usable source must provide:

- `meta/info.json`;
- episode and task metadata in supported Parquet or JSONL form;
- readable data Parquet files;
- at least two video features and readable referenced media;
- episode/frame totals that agree with metadata.

The catalog can still show unusable datasets so their validation reason can be
reviewed, but they cannot contribute episodes.

## Run the application

From an activated environment:

```bash
cd /home/ubuntu/harsha/datasets
PYTHONPATH=dataset_studio python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Alternatively, start it with the existing `lingbot` interpreter without
activating Conda:

```bash
cd /home/ubuntu/harsha/datasets
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> on the same machine. Keep the terminal running and stop the server with `Ctrl+C`.

When connecting over SSH, create a tunnel from your local computer:

```bash
ssh -L 8000:127.0.0.1:8000 ubuntu@YOUR_SERVER
```

Then open <http://127.0.0.1:8000> locally.

Confirm that the backend is healthy:

```bash
curl http://127.0.0.1:8000/api/health
```

Expected response:

```json
{"status":"ok"}
```

Do not expose the server publicly. It has no authentication and is designed for
trusted local use or access through an SSH tunnel.

## Quick usage

1. Start the app from the dataset root and open the browser.
2. Enter a local editor name in the workspace header.
3. Open **Sources**, rescan if needed, claim one dataset, and select **Open
   dataset**.
4. Complete **Cameras**, **Joints**, **Episodes**, and **Tasks** for that source.
5. Return to **Sources** and save an `approved` checkpoint.
6. Repeat for each dataset you want to include.
7. Review the combined selection in **Balance** and configure prompt/group
   caps.
8. Run **Preflight** and resolve every blocker.
9. Open **Export**, reconfirm the two final camera names, and start export.
10. When complete, use the output folder directly or prepare and download a
    `.tar.gz`.

## Curation workflow

The phase tabs are freely navigable. Dataset curation remains one dataset at a time; global balance and export only read shared checkpoints marked `approved`.

1. **Sources** — Find a dataset, claim it under your local profile, and open it. Quarantined/single-camera datasets cannot contribute episodes. Use **Exclude…** with a reason when a source should be explicitly omitted, and **History** to inspect immutable shared revisions.
2. **Output** — Set the output folder name and parent directory. The output always contains `wrist` plus one selected second canonical camera. Set an optional global maximum episodes per edited task.
3. **Cameras** — Preview a representative episode for every source view. Map exactly one view to `wrist`, exactly one to the configured second camera, and omit the rest.
4. **Joints** — Review the automatic mapping for both `action` and `observation.state`. Standard names and `main_...` aliases map automatically into `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, and `gripper`; manually correct a selector if a source uses another order.
5. **Episodes** — Browse thumbnails, stage candidates with gallery checkboxes,
   stage or unstage every usable episode on the current 60-episode page, load
   all camera videos for a focused episode, and move with Previous/Next.
   **Stage all usable** fills the temporary tray without changing the recipe;
   **Clear stage** empties only that tray. Use **Subtask groups** to stage an
   exact count for each source-prompt variant, the same count for every variant,
   or a balanced total cap for the subgroup.
6. **Tasks** — Review the temporary staged episode tray. Prepare one final
   prompt for every staged episode, include staged candidates in the real
   recipe, remove staged candidates from the recipe, or clear the stage.
7. Save an **approved checkpoint** in Sources when that dataset is ready. A draft is autosaved after mapping, selection, prompt, and flag changes, but drafts are not export inputs.
8. Release the claim. The shared checkpoint and its revision history remain available to the next local profile.

Claims only prevent two local profiles from editing the same dataset simultaneously. There is no login or authentication; use distinct profile names and treat the app as trusted-local software.

### Episode subtask sampling

The Episodes page clusters the currently open dataset's usable source prompts
with the same local deterministic embedding as Global Balance. This is a
read-only analysis of catalog metadata: it does not modify source prompts,
metadata, Parquet, or video.

Each cluster separately shows already-included episodes, newly staged episodes,
and remaining candidates. Expand it to set a separate new-candidate count for
every exact source-prompt variant, enter **New per variant** to use one count
across the cluster, or enter **Cap new candidates at** to stage one balanced
total across its variants. These group controls never re-stage an episode that
is already included in the recipe. Counts use a deterministic spread instead of
taking only the first consecutive episodes. A total subgroup cap allocates new
candidates round-robin across variants before taking extra examples from any one
variant.

Group controls, gallery checkboxes, page-wide controls, and focused-episode
prompt edits update only the temporary stage. They do not autosave or modify the
recipe. Open **Tasks** to inspect the staged episode list, prepare a shared
prompt, and explicitly include or exclude one row or choose **Include all
staged** / **Exclude all staged**. Gallery checkboxes can still deliberately
stage an already-included episode when you need to edit its final prompt or
remove it; only automatic group counts exclude included episodes.
Those commit actions update the recipe and trigger normal autosave. Prompt edits
never change source metadata or the source prompt used for grouping.

Large datasets are paged at 60 gallery episodes at a time, and subtask-variant
rows are created only when their cluster is expanded. Group-wide targets still
apply to every variant, including variants that are not currently expanded.
This avoids requesting hundreds or thousands of thumbnails during one render.

### Staged episode tray

Open **Tasks** after staging candidates. Every row is one staged episode and
shows its source task, staged final prompt, and whether it is already included
in the real recipe. Each row has **Include**, **Exclude**, and **Unstage**
actions. **Prepare prompt** changes the proposed final prompt for all staged
episodes without saving it yet. **Include all staged** adds or updates the whole
tray in one autosaved recipe change. **Exclude all staged** removes included
tray episodes from the recipe while keeping them staged. **Clear stage**
discards the temporary tray without changing the saved recipe. Source datasets
remain unchanged throughout.

The separate **Included episodes** section always lists the current dataset's
saved recipe choices, including episodes that are not in the temporary stage.
It is paged at 60 rows. Check individual rows or use **Check page**, then choose
**Exclude checked** to remove only that subset. Every row also has an individual
**Exclude** action. **Clear all included** removes every included episode from
the current dataset after confirmation. These removal actions preserve the
temporary stage.

## Named curation workspaces

The workspace control in the header lets you keep separate curation efforts in the same dataset root. A workspace owns only its users' local editor files, `claims.json`, and `dataset_checkpoints.json` (including checkpoint history). Project settings, export jobs and manifests, prepared downloads, source datasets, staging directories, and completed exports are global and are preserved when you create or switch a workspace.

Select **Save & start new…** to snapshot the current workspace and begin with empty users, claims, drafts, approvals, and checkpoint history. Enter a unique workspace name and the exact confirmation phrase `START NEW WORKSPACE`. To activate an existing workspace, select its destination, choose **Switch**, and enter `SWITCH WORKSPACE`. Both operations are unavailable while an export is queued, running, cancelling, or preparing an archive, so wait for that job to reach a terminal state first.

Snapshots are stored at `.dataset_studio/saved_workspaces/<workspace-id>/`; each includes `workspace.json` plus the workspace-owned state. After a successful create or switch, the browser resets its saved editor identity to `operator` and reloads. Enter the intended editor name again before resuming work.

### Manual workspace recovery

A transition writes and fsyncs `.dataset_studio/workspace_transition.json` before replacing active state. Snapshot files, restore trees, activation rename boundaries, and the registry replacement are also fsynced before that marker is removed. Symlinked `.dataset_studio` or workspace-owned state targets are refused rather than followed outside the dataset root. If the marker exists at startup, the app refuses to serve a potentially mixed workspace and reports HTTP 409 for recovery conflicts. Stop the app and do not delete or rename anything until the active registry and recovery copies have been inspected.

Preserve all of these paths that exist:

- root-level `.dataset_studio/.restore-*` staged targets;
- root-level `.dataset_studio/.rollback-*` copies of the pre-transition active targets;
- the root-level `.dataset_studio/workspace_transition.json` marker;
- `.dataset_studio/saved_workspaces/.recovery-*` prior saved snapshots.

Read the marker's operation, phase, workspace IDs, and exact restore/rollback paths. Compare `workspace_registry.json` with the active `claims.json`, `dataset_checkpoints.json`, and `workspaces/`, and inspect `workspace.json` in saved snapshots. Preserve the current active targets separately, then select one complete, internally consistent set of only those three workspace-owned targets. Do not copy or replace settings, jobs, manifests, downloads, exports, staging data, completed datasets, or source datasets. Remove the marker and obsolete recovery paths only after the active files and registry agree; restart the app and verify the registry, claims, checkpoint history, and user files before resuming curation. A malformed registry, or a registered snapshot that is missing, malformed, escapes `saved_workspaces/`, or identifies a different workspace, is also refused with HTTP 409 and must be repaired from these preserved copies.

## Output camera changes

`wrist` is mandatory. The second camera is selected in Output and reconfirmed in Export.

Changing the second camera invalidates the current preflight manifest. Camera mapping dropdowns immediately change to only:

- `Omit`
- `wrist`
- the newly configured second camera

Old targets are shown as requiring remapping. Reopen and remap every affected approved dataset, approve a new checkpoint revision, and rerun Preflight. The exporter does not silently substitute another view.

## Global balance

Balance calls the export preflight planner and aggregates every shared `approved` checkpoint. Draft and excluded checkpoints are omitted.

For each edited final prompt it shows:

- selected approved episodes;
- retained episodes after the project-wide cap;
- retention percentage.

The cap is deterministic: source dataset path and source episode index decide which episodes are retained. Change the cap in Output, save settings, and refresh Balance.

### Groq-assisted task-group names

Balance also creates deterministic local embeddings from the unchanged prompts in
approved checkpoints. The embedding features preserve task-defining differences
such as placing in a container, placing next to an object, placing between
objects, and directional movement. Draft and excluded prompts are not embedded.

To let Groq suggest concise names for these local clusters, set the API key in
the shell that starts the server:

```bash
export GROQ_API_KEY='your-key'
# Optional; this production model is the default:
export GROQ_TASK_GROUP_MODEL='llama-3.1-8b-instant'
```

Restart the server, open **Balance**, and choose **Generate names with Groq**.
One request names all current clusters. Only the task prompt strings and opaque
cluster IDs are sent; dataset paths, videos, Parquet data, checkpoints, users,
claims, and exports are not sent. The API key remains server-side and is never
returned to the browser.

Groq names are suggestions. Review or edit each name and choose **Approve
name**. Group names are workspace-specific and are stored separately at
`.dataset_studio/task_groups.json`; they never rewrite checkpoint recipes,
episode prompts, revision history, or exported prompts. Re-running suggestions
does not replace an approved group name. Switch **View** between grouped totals
and the existing individual-prompt balance table at any time.

Each group card also has a draggable **Final dataset group cap** slider and an
exact-number field. Releasing the slider or changing the number saves the cap
immediately and refreshes preflight. Set it to `0` to omit that group; set it to
the current maximum (or choose **Use all**) to remove the group cap. Export
first applies the Output page's per-prompt cap, then applies each group cap in
stable source-dataset-path and episode-index order. The resulting group caps and
selected/retained group counts are frozen into the export manifest. Caps are
workspace-specific metadata in `task_groups.json`, not checkpoint or prompt
edits.

If Groq is not configured, rate-limited, unavailable, or returns malformed or
incomplete JSON, the page keeps the existing approved names and saves no partial
response. Local clustering and individual-prompt balancing remain available.

Episode subtask grouping never calls Groq. Groq is used only when **Generate
names with Groq** is selected in Global Balance. The current naming safeguard
refuses more than 400 unique approved prompts before making an external request;
that local validation message is not a Groq rate-limit response.

## Preflight

Preflight freezes a manifest preview and blocks export for:

- missing or duplicate required camera mappings;
- incomplete, duplicate, or out-of-range six-joint action/state mappings;
- unreadable source Parquet or video;
- incompatible action or observation-state schemas;
- unknown, duplicate, or shorter-than-two-second episodes;
- blank final prompts;
- an invalid or already existing destination;
- no approved episodes;
- a camera choice that has not been successfully remapped.

Mapping changes vector order only. It never converts units or synthesizes a missing joint. A seven-position end-effector action is intentionally incompatible with the six-joint SO-101 output contract and must be excluded.

Blockers are grouped by checkpoint revision. Use each blocker’s phase button to return to the relevant source, camera, episode, balance, or output screen. When another dataset must be opened, the Sources catalog is filtered to that dataset so you can claim it safely.

The manifest preview shows source and output episode indices, edited task, canonical cameras, checkpoint revision, and last editor. No export can start until preflight has zero blockers.

## Final export

In Export:

1. Reconfirm the second camera.
2. If it differs from Output, apply it and rerun preflight. This deliberately invalidates incompatible mappings.
3. Check the confirmation box.
4. Select **Start LeRobot v2.1 export**.

Export runs as a persisted background job. The page may be refreshed without losing job state. Job cards show queued/running/cancelling/cancelled/failed/completed state, progress, current stage, dataset/episode/camera, failure details, manifest path, and final output path. Active jobs can be cancelled.

The two camera streams for each episode are encoded concurrently, so export can use roughly two CPU cores heavily. Output remains H.264/yuv420p at the configured fixed geometry and rate.

After a job is complete, choose **Prepare .tar.gz** only if you need a browser download. Archive creation is intentionally lazy: a normal export creates only the dataset folder. Once requested, the cached archive is stored at `.dataset_studio/downloads/<job-id>.tar.gz` and **Download .tar.gz** appears when it is ready. The archive contains one top-level dataset folder. Packaging temporarily duplicates the exported dataset on disk; repeated requests reuse the cached archive.

The exporter writes to `exports/.staging-<job-id>` (or the configured output parent) and only atomically publishes the final output after verification. A failed or cancelled staging directory is retained for diagnosis and is never presented as a valid dataset.

## Export structure

A successful export contains one Parquet and exactly two MP4 files per episode:

```text
OUTPUT/
├── data/
│   └── chunk-000/
│       └── episode_000000.parquet
├── videos/
│   └── chunk-000/
│       ├── observation.images.wrist/
│       │   └── episode_000000.mp4
│       └── observation.images.SECOND_CAMERA/
│           └── episode_000000.mp4
└── meta/
    ├── info.json
    ├── tasks.jsonl
    ├── episodes.jsonl
    ├── episodes_stats.jsonl
    ├── stats.json
    └── provenance.jsonl
```

The output is normalized to 30 FPS, 640×480, H.264/yuv420p. `episode_index`, global `index`, per-episode `frame_index`, timestamps, and edited-prompt `task_index` are rebuilt. The final verifier reopens every Parquet and video before the job becomes `completed`.

## Recovery and troubleshooting

**Source catalog remains on “Scanning…”**

Check that Uvicorn is still running:

```bash
curl http://127.0.0.1:8000/api/health
```

Expected:

```json
{"status":"ok"}
```

The first catalog request validates nested metadata and Parquet files and can take several seconds.

**Export page shows a failed job**

Read the failure details and manifest path on the job card. Correct the source/checkpoint/settings issue and start a new job. Failed staging output is intentionally retained; do not use it as a dataset.

**A job was `running` when the server stopped**

Restart the app and inspect the persisted job. Interrupted jobs are marked `failed`; their staging directory is retained for diagnosis. They never silently resume or become valid. After correcting any issue, start a new export.

**Output destination already exists**

Choose a new output folder name in Output. Existing output is never overwritten.

**A dataset is quarantined**

Expand it in Sources. The issue text identifies unreadable Parquet, metadata count mismatch, insufficient cameras, or another source problem.

**The page cannot be opened from another computer**

Use the SSH tunnel above. Do not expose the app on `0.0.0.0` unless the network is trusted and protected.

## Tests

Run the backend test suite:

```bash
cd /home/ubuntu/harsha/datasets
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python -m unittest discover -s dataset_studio/tests -v
```
