# Dataset Workspace `.gitignore` Design

## Goal

Keep application source, tests, documentation, and development review records
visible to Git while excluding downloaded datasets, generated exports, local
workspace state, caches, archives, and machine-specific files.

## Tracking boundary

At the repository root, all directories are ignored by default. The following
project directories are explicitly restored:

- `dataset_studio/`
- `docs/`
- `.superpowers/`

This makes every current and future top-level dataset directory ignored without
maintaining a growing list of dataset names. It also avoids globally ignoring
Parquet or video extensions, allowing deliberate test fixtures under tracked
project directories.

Root application scripts and tests remain trackable because the directory rule
does not exclude root files.

## Generated files

The ignore file also excludes:

- `.dataset_studio/` and `exports/`;
- `dataset_index.json`;
- root archives and packaged exports;
- Python bytecode, test, type-checker, and linter caches;
- virtual environments, coverage output, local environment files, editor
  metadata, and operating-system artifacts.

`.env.example` remains trackable as a safe configuration template.

## Verification

Use `git check-ignore -v` to prove that representative dataset, export,
workspace-state, cache, and index paths are ignored. Confirm with
`git status --short` that `.gitignore`, application source, tests,
documentation, and `.superpowers/` remain visible to Git.
