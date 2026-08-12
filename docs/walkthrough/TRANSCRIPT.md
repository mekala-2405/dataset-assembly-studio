# Dataset Assembly Studio — Video Transcript

Captioned transcript for `docs/walkthrough/output.mp4` (2 min 8 s, 1280×720).

The video is a screen tour of **Dataset Assembly Studio** recorded against the
real `dataset/` folder (5 datasets, 29 usable episodes) in the `demo_1`
workspace as `operator`. It pans down each phase screen in order:
Sources → Cameras → Joints → Episodes → Tasks → Sources (approve) → Balance →
Export. There is no narration; timestamps below match what appears on screen.

---

## [0:00] Intro — Sources catalog

Header bar: **LOCAL LEROBOT WORKBENCH**, workspace **demo_1**, working as
**operator**, actions for Save & start new, Switch, and Release all my claims.

- Tagline: *"Review, normalize, and curate without touching a source
  dataset."*
- Header metrics: **5 datasets · 5 valid · 29 usable episodes**.
- **Source catalog** with **Find a dataset** search (by name, task, camera)
  and **Sources folder** `/home/mekala/project/transfers` + **Use this
  folder**, showing *"Scanning /home/mekala/project/transfers"*.
- Dataset cards with version/FPS/camera/usable-episode stats and per-card
  actions: **Claim & open**, **Save draft**, **Approve checkpoint**,
  **Exclude…**, **History**, **Release claim**.
- Flag controls: **New flag name**, **Optional text rule**, **Add flag**.

## [0:05] Sources catalog — scrolling the cards

The catalog pans through the discovered sources grouped by folder:

- `dataset/Uni` — v3.0, 30 FPS, 3 cameras, 5/5 usable.
- `dataset/5ep` — v2.1, 30 FPS, 2 cameras, 5/5 usable.
- `dataset/assembled_lerobot_v21` — v2.1, 30 FPS, 2 cameras, 10/10 usable.
- `exports/new` and `exports/5ep` — v2.1, 30 FPS, 2 cameras, 4/4 and 5/5 usable.
- **PROJECT SETTINGS** and **CURRENT DATASET** sections appear as the page
  scrolls.

## [0:25] Cameras — mapping views to the export contract

**CURRENT DATASET** panel, contract **wrist + front**:

- **Camera mapping**: *"Map views for dataset/Uni. Each preview uses one
  representative episode from the actual source."*
- A source view is mapped to **observation.images.top** with an inline
  **Representative episode** player (video progress shows 0:08 / 2:59) and a
  **Map source view to** selector.
- `wrist` is fixed; exactly one view maps to `front`; unused views are omitted.

## [0:35] Joints — canonical six-joint order

**CURRENT DATASET · Joint mapping** for `dataset/Uni`:

- Status badge **6 + 6 mapped**: *"Both vectors map cleanly to the canonical
  six-joint order."*
- Table of the canonical output joints — `shoulder_pan`, `shoulder_lift`,
  `elbow_flex`, `wrist_flex`, `wrist_roll`, `gripper` — each with an
  **ACTION SOURCE** and **STATE SOURCE** dropdown (`o.shoulder_pan.pos`,
  `o.shoulder_lift.pos`, `2.elbow_flex.pos`, …).
- *"Suggested mappings are filled automatically; change a selector only when
  the source order is different."*

## [0:39] Episodes — assembly tray and diversity sampler

**Assembly tray** with **Stage all usable**, **Clear stage**, and **Check
current dataset**; tray stats: included episodes, staged episodes, edited
tasks.

**DIVERSITY SAMPLER · Subtask groups**:

- *"Build a temporary stage with exact per-variant counts or a total subgroup
  cap. Nothing enters the real recipe until you commit it in Tasks."*
- Local cluster **Place · container** (1 source-prompt variant, 1 local group).
- Per-variant **New per variant** / **Stage new per variant** with an exact
  **Count**, and **Cap new candidates at** / **Stage new total** for a
  subgroup-wide total.
- Variant row: *"Take the red block and put it in the white box"* — 5 new
  staged, 0 included, 5 candidates left, with a **Stage** button.

## [1:01] Episodes — episode gallery

**Episode gallery**, paged 1 of 1 (5 of 5 episodes), showing **Episode 0**
(34.6 s, *"Take the red block and put it in the white box"*):

- *"Checkboxes add candidates to the temporary stage"*; **Stage page** /
  **Unstage page**, **← Previous / Next →**, and **Load all available views**
  for the focused episode.

## [1:26] Tasks — committing the stage to the recipe

- Tray shows **5 staged episodes**, 0 included, 0 edited tasks.
- Toolbar: **Prepare prompt** (one shared prompt for every staged episode),
  **Include all staged**, **Exclude all staged**, **Clear stage**.
- A toast confirms: *"Episode 0 is now excluded from the real recipe."* with
  the episode row showing **Include / Exclude** controls.
- Camera preview cards ready to load for `observation.images.gripper`,
  `observation.images.top`, and `observation.images.right_side`.

## [1:35] Sources — approving a checkpoint

Back on the Sources catalog (**Rescan folder**, "Scanning…" over
`/home/mekala/project/transfers`) with dataset cards showing validation
status `ready` and the checkpoint actions (Claim & open, Save draft, Approve
checkpoint, Exclude…, History, Release claim) before approval.

## [1:00] Balance — combining approved checkpoints

**ALL APPROVED CHECKPOINTS · Global balance**:

- *"Draft and excluded checkpoints never enter these counts."*
- Metrics: **4 approved selections · 4 retained · 1 edited task**; no per-task
  cap configured, task-group caps active. **Refresh approved data** reloads
  from the frozen approvals.
- **LOCAL CLUSTERS · GROQ NAMES · Task groups** (view: Grouped tasks):
  - **Generate names with Groq** — *"Local embeddings are ready. Groq model:
    llama-3.1-8b-instant. Names are suggestions until approved."*
  - Group **place · container** (UNLABELED) with **Group name** + **Approve
    name**; *"Review or enter a concise group name."*
  - **Final dataset group cap** slider at **All 4** with **Use all**: *"Applied
    after the per-prompt cap. Set 0 to omit this group; maximum means no group
    cap."* Expandable **View 1 unchanged prompt**.
- Individual prompt table with **EDITED TASK / SELECTED / RETAINED /
  RETENTION** columns.

## [1:14] Export — final handoff and jobs

**FINAL HANDOFF · Export**, badge **Preflight ready**:

- *"Reconfirm the two-camera contract, then run the verified export in the
  background."*
- **CAMERA 01 · wrist** (Fixed) and **CAMERA 02 · front** (must match Output
  settings).
- Confirmation: *"I confirm this export includes every approved checkpoint
  that passes the global task cap, with exactly these two cameras."*
- Manifest line: *"Manifest ready: 4 episodes will be normalized to wrist +
  front."* Buttons: **Rerun preflight**, **Start LeRobot v2.1 export**.

**Export jobs** panel (**Refresh jobs**) with persisted job cards showing a
Queued → Running → Cancelled / Completed lifecycle:

- **Running**: 0/4 episodes — normalizing videos (dataset/Uni episode 1:
  wrist + front), progress 0%, **Cancel export**; output
  `/home/mekala/project/transfers/exports/test`, manifest
  `….manifest.json`.
- **Cancelled**: 1/15 episodes — normalizing videos, 7%; *"export cancelled;
  staging data retained."*
- **Completed**: 4/4, 5/5, and 10/10 episodes (outputs `/new`, `/5ep`,
  `/assembled_lerobot_v21`) with **Prepare .tar.gz** / **Download .tar.gz**
  actions.
