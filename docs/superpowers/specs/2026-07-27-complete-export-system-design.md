# Complete Export System Design

## Scope

Build the remaining Dataset Assembly Studio functionality as a trusted-local, multi-user curation and export system. Local profile names remain sufficient; no authentication is added.

## Project settings

The Start/Output phase stores output dataset name, output parent directory, mandatory canonical `wrist` camera, one user-selected second canonical camera, 30 FPS, 640×480 resolution, H.264 video, and a manual global maximum episodes per edited task. Final Export repeats the camera choice and reruns preflight whenever it changes.

## Export inputs

Export includes every shared checkpoint whose status is `approved`. Draft and excluded checkpoints are omitted. Approved checkpoints retain edited prompts, selected source episodes, source-to-canonical camera mappings, flags, checkpoint revision, and last editor.

## Global planning and balance

The planner deduplicates source dataset/episode pairs, groups selected episodes by edited final prompt, and applies the manual task cap deterministically in source-path/episode order. It creates an immutable manifest containing exact source references, output indices, output task indices, camera mappings, and checkpoint revisions.

## Blocking preflight

Export stops rather than silently dropping data when any approved checkpoint has:

- missing `wrist` or selected second camera mapping;
- missing or unreadable source Parquet/video;
- action or observation-state shape/name incompatibility;
- an episode shorter than two seconds;
- blank final prompt;
- duplicate source episode;
- invalid or existing output destination;
- a final camera choice different from the project choice without successful remapping.

Errors are grouped by checkpoint and link back to the appropriate phase.

## LeRobot v2.1 output

Output uses one episode Parquet and two MP4 files per episode:

```text
data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet
videos/chunk-{episode_chunk:03d}/observation.images.wrist/episode_{episode_index:06d}.mp4
videos/chunk-{episode_chunk:03d}/observation.images.{second_camera}/episode_{episode_index:06d}.mp4
```

`episode_index` is contiguous globally. `frame_index` resets per episode. `index` is contiguous globally. `timestamp` is regenerated at 30 FPS. `task_index` is rebuilt from unique edited prompts. Action/state values remain float32 and all index fields use int64.

The exporter regenerates `info.json`, `tasks.jsonl`, `episodes.jsonl`, `episodes_stats.jsonl`, aggregate statistics, and `provenance.jsonl`.

## Video handling

PyAV decodes source segments, seeks to episode timestamps when source video is sharded, resamples to 30 FPS, scales/letterboxes to 640×480 without stretching, and encodes H.264/yuv420p. Cancellation is checked while decoding and between cameras/episodes.

## Jobs and recovery

Export runs in a local background thread. Job state is persisted under `.dataset_studio/jobs/<job_id>.json` with queued/running/cancelling/cancelled/failed/completed states, current dataset/episode/camera, counts, error, manifest path, staging path, and final path.

Output writes to `exports/.staging-<job_id>`. A completed staging directory is verified and atomically renamed to the final destination. Failed/cancelled staging is retained and clearly marked; it is never treated as valid output.

## Verification

Verification reopens every Parquet and video and checks contiguous indices, row counts, task references, metadata totals, two decodable videos per episode, duration/frame agreement, schema consistency, and provenance coverage. Only verified jobs become completed.

## Revision and exclusion history

Shared checkpoint updates append immutable revision records in addition to updating the latest checkpoint. Exclusions require a reason and remain visible in reporting. Claims control write access but do not delete or hide shared checkpoint history.

## UI

Output/Start configures project settings. Global Balance shows selected/retained counts across all approved checkpoints. Preflight lists blocking errors. Final Export confirms cameras/settings, starts a job, and shows progress, current work, cancellation, failure details, and completed output path.
