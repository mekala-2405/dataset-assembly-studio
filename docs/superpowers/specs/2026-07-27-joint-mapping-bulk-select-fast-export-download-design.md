# Joint Mapping, Bulk Selection, Faster Export, and Lazy Download

## Scope

Extend Dataset Assembly Studio with canonical joint mapping, bulk episode
selection, faster video export, and an on-demand `.tar.gz` download. Source
datasets remain read-only and all changes remain part of shared checkpoint
recipes and immutable revision history.

## Workflow

The freely navigable phases become:

1. Sources
2. Output
3. Cameras
4. Joint Mapping
5. Episodes
6. Tasks
7. Balance
8. Preflight
9. Export

Opening a source still starts at Cameras. The user proceeds to Joint Mapping,
then Episodes. Export remains unavailable until all approved checkpoints pass
preflight.

## Canonical joint contract

The exported `action` and `observation.state` vectors both use this six-element
order and metadata:

1. `shoulder_pan.pos`
2. `shoulder_lift.pos`
3. `elbow_flex.pos`
4. `wrist_flex.pos`
5. `wrist_roll.pos`
6. `gripper.pos`

One joint-mapping control per dataset contains separate `action` and
`observation.state` position maps. Both maps target the same canonical order.
They reorder values only; they do not convert units or synthesize missing
values.

### Automatic mapping

When a dataset is first opened, the backend proposes a mapping from feature
metadata. Known aliases include the canonical `.pos` names and the
`main_shoulder_pan`, `main_shoulder_lift`, `main_elbow_flex`,
`main_wrist_flex`, `main_wrist_roll`, and `main_gripper` names. Matching is
case-insensitive and normalizes punctuation and the `main_` prefix.

The Joint Mapping UI displays each canonical slot with separate source
selectors for `action` and `observation.state`, prefilled from the proposal.
The user may manually change either source position. The saved recipe retains
both maps so genuine source differences remain explicit.

Preflight requires an exact one-to-one mapping of all six positions for both
features. It blocks duplicates, omissions, out-of-range positions, incompatible
vector lengths, and approved checkpoints saved before joint mapping was
completed. Seven-element end-effector actions such as `delta_eef.*` are not
silently converted and remain blocked.

## Checkpoint recipe

Each dataset recipe adds:

```json
{
  "joint_mapping": {
    "action": {
      "shoulder_pan.pos": 0,
      "shoulder_lift.pos": 1,
      "elbow_flex.pos": 2,
      "wrist_flex.pos": 3,
      "wrist_roll.pos": 4,
      "gripper.pos": 5
    },
    "observation.state": {
      "shoulder_pan.pos": 0,
      "shoulder_lift.pos": 1,
      "elbow_flex.pos": 2,
      "wrist_flex.pos": 3,
      "wrist_roll.pos": 4,
      "gripper.pos": 5
    }
  }
}
```

Auto-proposals are saved through the existing autosave path after the user
opens the Joint Mapping phase. Every manual change autosaves and invalidates
the global preflight manifest.

## Bulk episode selection

Episodes adds two controls above the gallery:

- **Select all usable episodes** selects every episode in the open dataset that
  is valid and at least two seconds long.
- **Clear selection** removes every selected episode in the open dataset.

Select All initializes newly selected episodes with their original task prompt
and leaves existing edited prompts unchanged. Both operations update counters,
gallery state, task summaries, and the checkpoint using one debounced autosave
rather than one save per episode.

## Export performance

The completed 11-episode job processed approximately 150 seconds of source
footage into 22 normalized videos in 86.6 seconds. The current implementation
encodes those videos sequentially.

For each episode, the exporter runs the two independent camera normalizations
in parallel with two workers. Each worker opens its own PyAV input/output
containers. H.264 output remains 30 FPS, 640×480, and yuv420p, using the
`veryfast` preset and CRF 20. Episode-level ordering, cancellation, metadata,
and final verification remain unchanged.

The job records its current stage (`data`, `videos`, `metadata`, `verification`,
or `archive`) and camera completion counts so progress remains understandable
when cameras run concurrently. Parallelism is limited to two camera workers to
bound memory and CPU use.

No stream-copy path is added because imprecise keyframe boundaries could break
frame-count and duration verification.

## Lazy `.tar.gz` download

Successful export continues to publish only the dataset directory. It does not
create an archive automatically.

A completed job shows **Prepare .tar.gz**. Pressing it starts a separate
persisted background archive task and immediately returns control to the UI.
The job reports archive state (`not_requested`, `preparing`, `ready`, or
`failed`). Once ready, the UI shows **Download .tar.gz**.

Archives are stored under:

```text
.dataset_studio/downloads/<job-id>.tar.gz
```

The archive contains one top-level directory named after the exported dataset.
Repeated downloads reuse the cached archive. Only completed job outputs may be
archived, and paths are resolved from persisted job records rather than
user-provided filesystem paths. Archive failures do not alter the completed
dataset or export status.

## API additions

- `GET /api/datasets/joint-contract?dataset_path=...` returns source feature
  names, shapes, canonical names, and the automatic proposal.
- Existing checkpoint APIs save `joint_mapping` in the recipe.
- Existing preflight responses include joint mapping errors and the frozen
  mapping in each manifest episode.
- `POST /api/export/jobs/{job_id}/archive` starts lazy archive preparation.
- `GET /api/export/jobs/{job_id}/download` returns the ready `.tar.gz`.

The existing job status/list endpoints include archive state, archive error,
archive path when ready, current stage, and camera progress.

## Error handling

- Joint metadata without usable names receives no automatic proposal and
  requires manual mapping.
- Duplicate or incomplete mappings block checkpoint approval and preflight.
- Action and state may map differently, but each must independently map all six
  canonical slots exactly once.
- Seven-dimensional end-effector actions remain incompatible.
- Cancelling export stops both camera workers cooperatively and retains staging.
- Archive creation uses a temporary file followed by atomic rename. Interrupted
  or failed temporary archives are not offered for download.
- A missing completed output changes archive state to failed with a clear
  message.

## Testing

Automated tests cover:

- alias-based proposals and unknown-name behavior;
- one-to-one mapping validation;
- action and state vector reordering and canonical metadata;
- 7D action rejection;
- Select All semantics through pure selection helpers or rendered browser
  interaction;
- two concurrent camera tasks, cancellation, and unchanged final verification;
- lazy archive lifecycle, top-level archive structure, caching, safe completed
  job lookup, and download response;
- API contracts and complete regression suite.

Rendered QA covers desktop and 390px mobile layouts, phase navigation, automatic
joint mapping edits, bulk selection counters, export progress, and archive
button state.
