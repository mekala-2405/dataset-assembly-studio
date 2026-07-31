# Autosave, Handoff, and Balance Design

Opening or claiming a dataset starts in Cameras. The current dataset recipe is loaded from the latest shared checkpoint, so a new owner inherits prior work.

Every camera mapping, episode select/deselect, prompt edit, dataset flag, required-camera change, and balance-limit change schedules a debounced draft save. The fixed status banner reports Saving, Saved with revision, or Save failed. Modifying an approved checkpoint returns it to draft.

Shared checkpoints persist independently of claims. Releasing one or all claims removes ownership only; recipe data and revision history remain available.

Episodes displays live counts for selected episodes and distinct edited tasks. Balance owns the per-task cap and displays selected counts grouped by edited final task.
