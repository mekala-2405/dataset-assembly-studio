### Task 4: Documentation and complete verification

**Files:**
- Modify: `dataset_studio/README.md`
- Modify: `docs/superpowers/plans/2026-07-27-named-curation-workspaces.md`

**Interfaces:**
- Consumes: all prior tasks.

- [ ] **Step 1: Document workspace behavior and recovery**

Add a README section explaining:

- workspace-owned versus global state;
- create and switch confirmations;
- active-job blocking;
- saved snapshot path;
- browser editor reset;
- manual recovery from `.recovery-*` directories.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
PYTHONPATH=dataset_studio /home/ubuntu/miniforge3/envs/lingbot/bin/python \
  -m unittest discover -s dataset_studio/tests -v
```

Expected: all tests pass with zero failures.

- [ ] **Step 3: Run rendered desktop and mobile QA**

Browser plugin availability must be checked first. If absent, use the installed
headless Chrome fallback without adding dependencies. At 1440×1000 and
emulated 390×844:

1. verify page identity and non-blank content;
2. open the new-workspace dialog;
3. verify warning text and initially disabled action;
4. enter names and an incorrect phrase and keep the action disabled;
5. enter `START NEW WORKSPACE` and enable the action;
6. cancel without changing real workspace state;
7. open the switch dialog and verify destination naming;
8. confirm no relevant console errors or horizontal document overflow.

- [ ] **Step 4: Execute a temporary-root end-to-end state round trip**

Against a temporary dataset root, create a named workspace, write distinct
checkpoint/user data in the new workspace, switch to the old workspace, then
switch back. Verify both states and all global sentinel files after each
transition. Do not run this mutation check against the user's real
`.dataset_studio`.

- [ ] **Step 5: Mark plan complete from fresh evidence**

Check each plan item only after the corresponding command/output or rendered
interaction has been observed. Record any untested production-scale
concurrency risk rather than claiming it was exercised.
