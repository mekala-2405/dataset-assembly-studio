# Dataset Assembly Studio Design

Build a local web application that scans all LeRobot datasets under the datasets directory, validates their usable episodes, previews selections, and exports a normalized LeRobot v2.1 dataset.

The catalog treats each `meta/info.json` as a dataset root, including nested datasets. Broken sources are excluded when their Parquet, episode metadata, frame counts, or required video streams fail validation. Cautionary folder names are notes only. Prior merged datasets are marked derived.

An export defines one or two canonical camera slots. Users map each source camera to a slot or omit it; all selected episodes must provide the required slots. Output videos are 640x480 at 30 FPS. Users can edit source task prompts before export, and deterministic balancing uses the edited task labels. Episodes shorter than two seconds are excluded.

The exporter writes a new LeRobot v2.1 dataset, reindexed metadata, regenerated stats, and a provenance manifest mapping output episodes to their sources, mappings, prompts, and quality decisions.
