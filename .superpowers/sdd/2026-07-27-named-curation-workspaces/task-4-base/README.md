# Dataset Assembly Studio

Local web workspace for inspecting SO-101 LeRobot datasets, curating them one at a time, and exporting every approved checkpoint as one verified LeRobot v2.1 dataset.

Source datasets are never modified. Drafts, approvals, claims, settings, export manifests, and job state are stored beneath `.dataset_studio/`.

## Start the app

Use the `lingbot` environment because it contains PyArrow and PyAV:

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

## Curation workflow

The phase tabs are freely navigable. Dataset curation remains one dataset at a time; global balance and export only read shared checkpoints marked `approved`.

1. **Sources** — Find a dataset, claim it under your local profile, and open it. Quarantined/single-camera datasets cannot contribute episodes. Use **Exclude…** with a reason when a source should be explicitly omitted, and **History** to inspect immutable shared revisions.
2. **Output** — Set the output folder name and parent directory. The output always contains `wrist` plus one selected second canonical camera. Set an optional global maximum episodes per edited task.
3. **Cameras** — Preview a representative episode for every source view. Map exactly one view to `wrist`, exactly one to the configured second camera, and omit the rest.
4. **Joints** — Review the automatic mapping for both `action` and `observation.state`. Standard names and `main_...` aliases map automatically into `shoulder_pan`, `shoulder_lift`, `elbow_flex`, `wrist_flex`, `wrist_roll`, and `gripper`; manually correct a selector if a source uses another order.
5. **Episodes** — Browse thumbnails, load all camera videos for a focused episode, move with Previous/Next, select episodes, and edit final task prompts. **Select all usable** includes every valid episode of at least two seconds while preserving existing prompt edits; **Clear selection** affects only the open dataset.
6. **Tasks** — Review edited prompt counts for the currently open dataset.
7. Save an **approved checkpoint** in Sources when that dataset is ready. A draft is autosaved after mapping, selection, prompt, and flag changes, but drafts are not export inputs.
8. Release the claim. The shared checkpoint and its revision history remain available to the next local profile.

Claims only prevent two local profiles from editing the same dataset simultaneously. There is no login or authentication; use distinct profile names and treat the app as trusted-local software.

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
