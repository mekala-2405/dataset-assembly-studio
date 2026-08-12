# Dataset Assembly Studio — Feature Walkthrough

A guided tour of every feature in **Dataset Assembly Studio**, the local web
app for reviewing, curating, balancing, and exporting SO-101 LeRobot datasets
as one verified LeRobot v2.1 dataset.

> **Watch it instead:** `walkthrough/output.mp4` is a captioned,
> auto-generated screen tour of the same flow below. The stills used for the
> video live in `walkthrough/shots/`, and a timestamped transcript lives in
> `walkthrough/TRANSCRIPT.md`.
>
> This walkthrough was recorded against the real `dataset/` folder on this
> machine (3 datasets, 20 usable episodes) with the `operator` profile, so every
> step below is reproducible exactly as shown.

---

## The big picture

Sources are **never modified**. All of your work — drafts, approvals, claims,
camera/joint mappings, episode choices, final prompts, task-group caps, export
manifests, and job state — lives under `.dataset_studio/`. The app is a
trusted-local tool: no login, run over `localhost` or an SSH tunnel, single
user at a time per dataset via lightweight *claims*.

The workflow is a strict pipeline of nine phase tabs:

```
1 Sources → 2 Output → 3 Cameras → 4 Joints → 5 Episodes → 6 Tasks
         → 7 Balance → 8 Preflight → 9 Export
```

---

## 1. Sources — find, claim, and approve datasets

![Sources](walkthrough/shots/01-intro.png)

- **Sources folder** (`#sources-root` + **Use this folder**): point the app at
  the folder that *contains* your LeRobot dataset folders (each dataset has its
  own `meta/info.json`). Recursive discovery validates Parquet, metadata,
  camera count, and episode durations.
- **Header metrics** show `datasets / valid / usable episodes` at a glance, and
  the **Find a dataset** search filters name, task, camera, and more.
- Each dataset card (`#catalog`) reports version, FPS, camera count, usable
  episodes, and its validation status — `ready` or `quarantined` (with the
  reason spelled out). Quarantined datasets can be inspected but never enter an
  export.
- Cards are grouped by **source folder** (collapsible), and each card exposes
  the full set of checkpoint actions:

![Dataset card actions](walkthrough/shots/02-sources-actions.png)

| Action | What it does |
| --- | --- |
| **Claim & open** | Claims the dataset under your local profile and jumps to Cameras. Prevents two editors from editing the same dataset at once. |
| **Save draft** | Persists your current recipe as a non-export-input draft. |
| **Approve checkpoint** | Freezes an immutable, versioned (`r1`, `r2`, …) approved revision that becomes an export input. |
| **Exclude…** | Marks the source excluded with a required reason. Excluded checkpoints never contribute episodes. |
| **History** | Shows the immutable shared revision history for the dataset. |
| **Release claim** | Hands the dataset back; saved drafts and approvals remain available to the next profile. |

- **Header controls**: enter your editor name in *Working as* (stored per
  browser), **Release all my claims**, **Rescan folder**, and the **named
  workspace** selector (see below).
After approving, the card shows the immutable revision badge; from here on the
dataset contributes to Global Balance and export:

![Approved checkpoint](walkthrough/shots/08-sources-approved.png)

- **Flags**: define reusable flags (`#flag-name`, optional text rule, **Add
  flag**) and tag datasets with them (`Ctrl+1`…`Ctrl+9` on a hovered card).
  Flags are recipe metadata that follows a dataset into its checkpoint.

### Named workspaces

The header workspace control keeps separate curation efforts in the same
dataset root. A workspace owns only editor files, claims, and checkpoint
history; settings, exports, jobs, and sources are global.

- **Save & start new…** snapshots the current workspace and starts a blank one
  (requires typing the exact phrase `START NEW WORKSPACE`).
- **Switch** activates another saved workspace (requires `SWITCH WORKSPACE`).
- Transitions are fsynced and guarded by `workspace_transition.json`; a leftover
  marker blocks serving a mixed workspace with HTTP 409 until recovered
  manually per the README.

---

## 2. Output — define the export contract

![Output](walkthrough/shots/03-output.png)

- **Dataset folder name** and **Output parent directory**: the final verified
  dataset destination. Existing destinations are never overwritten.
- **CAMERA 01 · wrist** is fixed and mandatory in every approved dataset.
- **CAMERA 02** selectable — the canonical second camera (default `front`)
  exported alongside `wrist` for every episode.
- **Maximum episodes per edited task**: an optional project-wide cap applied
  deterministically in Balance/Preflight.
- Saving settings marks preflight **stale**. If you change the second camera,
  the app warns that every approved dataset must be remapped and re-approved
  before the next export.

---

## 3. Cameras — map source views to the export contract

![Cameras](walkthrough/shots/04-cameras.png)

Opened automatically when you claim & open a dataset. Each source view gets a
card with a **Load preview** button (plays a representative usable episode
from the actual source video) and a dropdown to map it to `wrist`, the second
camera, or **Omit**.

- Exactly **one** view must map to `wrist` and exactly **one** to the second
  camera — anything else is a preflight blocker.
- If the second camera changed since your last mapping, stale targets are
  flagged **"no longer in the output contract"** and must be remapped.
- Mapping choices autosave as a draft (see the **save banner** and autosave
  indicator in the header).

---

## 4. Joints — canonicalize the six-joint order

![Joints](walkthrough/shots/05-joints.png)

`action` and `observation.state` are exported in the same canonical order:
`shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper`.

- Standard names and `main_…` aliases map **automatically** — the header shows
  `6 + 6 mapped`, `Needs review`, or `Incompatible`.
- Each canonical joint row has two source-position dropdowns (Action source and
  State source). Manually correct a selector only when the source stores joints
  in another order.
- Mapping changes **reorder vectors only** — units are never converted and a
  missing joint is never synthesized. A seven-joint end-effector action is
  structurally incompatible with the six-joint output contract and must be
  excluded.
- Structurally broken datasets show a red notice and cannot be approved.

---

## 5. Episodes — stage candidates and sample subtasks

![Episodes](walkthrough/shots/06-episodes.png)

The biggest screen. It has four regions:

1. **Assembly tray stats** — included episodes, staged episodes, edited tasks.
   Buttons: **Stage all usable**, **Clear stage**, **Check current dataset**
   (client-side recipe validation).
2. **Subtask groups** (Diversity sampler) — clusters the open dataset's source
   prompts with the same deterministic local embedding used by Global Balance.
   - Per-cluster **New per variant** stages one count across every subtask
     variant, **Cap new candidates at** stages a balanced total across a group
     (round-robin across variants), and each expanded variant row has an exact
     count + **Stage** button.
   - Counts use a **deterministic spread** (never just the first N episodes) and
     never re-stage already-included episodes. Nothing here touches the recipe —
     it fills the *temporary stage* only.
3. **Episode gallery** — paged at 60, with thumbnails, direct **Stage episode**
   checkboxes, page-wide **Stage page / Unstage page**, and Previous/Next.
   Focused episodes show duration, task prompt, and include/stage state.
4. **Episode detail** — load **all camera views** for a focused episode, edit
   the staged final prompt inline, toggle stage, or step Previous/Next.

---

## 6. Tasks — review the stage and commit to the recipe

![Tasks](walkthrough/shots/07-tasks.png)

- **Staged episode tray**: every row is one staged episode with its source task,
  proposed final prompt, and whether it is already included.
- **Prepare prompt** sets one shared final prompt for all staged episodes.
- **Include all staged** commits the whole tray into the real recipe (autosaved
  draft). **Exclude all staged** removes included tray episodes while keeping
  them staged. **Clear stage** discards the tray only.
- Rows also have individual **Include / Exclude / Unstage**.
- **Included episodes** section (below) is independent of the stage — it always
  shows what's actually saved. **Check page**, **Clear checked**, **Exclude
  checked**, and **Clear all included** operate on the real recipe and preserve
  the temporary stage.

---

## 7. Balance — combine every approved checkpoint

![Balance](walkthrough/shots/09-balance.png)

Balance aggregates **all shared `approved` checkpoints** (drafts and exclusions
are ignored) and shows per edited task: selected episodes, retained after the
project cap, and retention percentage.

- **Refresh approved data** rebuilds counts from the frozen approvals.
- **Task groups** pane: local deterministic clusters of unchanged prompts with
  three features per group card:
  - **Generate names with Groq** — sends only prompt text + opaque cluster IDs
    to Groq (requires `GROQ_API_KEY`; the API key never leaves the server).
    Names are *suggestions* until you **Approve name**; re-running never
    replaces an approved name. A local safeguard refuses > 400 unique prompts.
  - **Final dataset group cap** — a draggable slider / exact number per group,
    applied *after* the per-prompt cap, in stable source-path + episode-index
    order. `0` omits the group; the maximum (or **Use all**) removes the cap.
    Group caps are workspace-specific metadata, never prompt edits.
  - **View prompts** lists every unchanged prompt in the group with its
    selected/retained counts.
- Toggle **View** between *Grouped tasks* and the classic *Individual prompts*
  table at any time.

---

## 8. Preflight — blocking validation and frozen manifest

![Preflight](walkthrough/shots/10-preflight.png)

Nothing is silently dropped. **Run preflight** checks, across every approved
checkpoint revision:

- missing/duplicate required camera mappings and incompatible joint mappings;
- unreadable Parquet/video, schema mismatches, and seven-joint actions;
- unknown, duplicate, or shorter-than-two-second episodes and blank prompts;
- invalid or already-existing destinations; no approved episodes.

- Blockers are grouped by checkpoint revision with a **Go to…** button per
  blocker that jumps you to the exact phase/dataset to fix it.
- The **Frozen manifest preview** shows output/source indices, edited task,
  cameras, revision, and last editor for the first 20 retained episodes.
- Zero blockers → the badge flips to `ready` and the Export phase unlocks.

---

## 9. Export — verified background export

![Export](walkthrough/shots/11-export.png)

1. **Reconfirm** the two-camera contract (`wrist` + second camera). If it
   differs from Output settings, **Apply camera & rerun preflight** — changing
   it deliberately invalidates incompatible mappings.
2. Check the confirmation box; the **Start LeRobot v2.1 export** button enables
   only when preflight is ready and non-stale.
3. Export runs as a **persisted background job** — refresh the page freely,
   cancel any active job, and read progress, current stage, dataset/episode/
   camera, manifest path, and final output path on the job card.

![Jobs](walkthrough/shots/12-jobs.png)

- The two camera streams are encoded **concurrently** (H.264/yuv420p,
  640×480 @ 30 FPS), so export uses roughly two CPU cores heavily.
- Output is normalized: rebuilt indices, timestamps, edited-prompt task indices,
  statistics, and provenance. `episode_index`, global `index`, and per-episode
  `frame_index` are all rewritten.
- Staging happens in `exports/.staging-<job-id>` and is only published
  **atomically after verification** — the final verifier reopens every Parquet
  and video before the job becomes `completed`. Failed staging is retained for
  diagnosis and never presented as valid.
- **Prepare .tar.gz** lazily packages the dataset for download and caches the
  archive at `.dataset_studio/downloads/<job-id>.tar.gz`; **Download .tar.gz**
  appears when ready.

### Output structure

```
OUTPUT/
├── data/chunk-000/episode_000000.parquet          # rebuilt index/frames/task_index
├── videos/chunk-000/
│   ├── observation.images.wrist/episode_000000.mp4
│   └── observation.images.<SECOND>/episode_000000.mp4
└── meta/  info.json · tasks.jsonl · episodes.jsonl
           · episodes_stats.jsonl · stats.json · provenance.jsonl
```

---

## Headless notes (used to record the video)

The video and stills were generated automatically against the running app:

1. Start the server: `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000`
   (from `dataset_studio/`).
2. Drive a real end-to-end session with Playwright — set the sources folder,
   claim & open the `5ep` dataset, map wrist + front cameras, auto-map joints,
   stage all episodes, prepare a shared prompt, include all staged, approve a
   checkpoint, refresh balance, run preflight, and arm the export screen.
3. Capture a full-page PNG per scene, then assemble a captioned 1280×720 video
   with an ffmpeg vertical-pan + fade pipeline.

The capture script (`capture.js`), scene manifest (`scenes.json`), and video
builder (`build_video.py`) are reusable if you want to re-record against your
own datasets.
