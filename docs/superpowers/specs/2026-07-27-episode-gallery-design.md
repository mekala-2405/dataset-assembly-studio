# Episode Gallery Design

Replace the episode card list with a two-pane review workspace. A compact gallery lists every episode with a representative non-wrist thumbnail, task description, duration, and selected state. Clicking a gallery item opens one focused episode in the detail pane.

The representative camera preference is `desk_view`, then `top`, then `front`, then any other camera whose name does not contain `wrist`. Wrist views are never used for gallery thumbnails unless a dataset has no non-wrist video at all, in which case the card displays a neutral placeholder.

The detail pane shows the original task, editable final task, select/deselect control, and Previous/Next navigation. All indexed source camera views are listed independently. A single Load all views action loads every available camera, and unavailable cameras show an explicit error.

Gallery selection and focused episode state are separate. Selecting an episode never replaces the focused episode or creates a duplicate editor. Prompt edits are stored directly in the selected episode recipe.

The UI remains lazy: gallery thumbnails load only near the viewport and full videos load only after Load all views. Controls have dedicated layout regions and cannot overlap.
