const DEFAULT_SETTINGS = {
  output_name: 'assembled_lerobot_v21',
  output_parent: 'exports',
  second_camera: 'front',
  max_per_task: null,
  required_cameras: ['wrist', 'front'],
  fps: 30,
  width: 640,
  height: 480,
  codec: 'h264',
};

const EPISODE_GALLERY_PAGE_SIZE = 60;
const INCLUDED_EPISODE_PAGE_SIZE = 60;

const state = {
  catalog: [],
  choices: new Map(),
  mappings: {},
  jointMappings: {},
  jointContracts: {},
  flags: [],
  datasetFlags: {},
  activeDataset: null,
  currentDataset: null,
  focusedEpisode: null,
  user: localStorage.getItem('dataset-studio-user') || 'operator',
  checkpoints: {},
  sharedCheckpoints: {},
  claims: {},
  workspaceRegistry: null,
  selectedWorkspaceId: null,
  saveTimer: null,
  currentSave: null,
  dirtyVersion: 0,
  dirty: false,
  workspaceTransitionPromise: null,
  workspaceTransitionPending: false,
  settings: { ...DEFAULT_SETTINGS },
  settingsLoaded: false,
  preflight: null,
  preflightStale: true,
  preflightReason: 'Run preflight after reviewing Output settings.',
  taskGroups: null,
  taskGroupsLoading: false,
  taskGroupCapSaving: new Set(),
  balanceViewMode: localStorage.getItem('dataset-studio-balance-view') || 'groups',
  episodeGroups: {},
  episodeGroupsLoading: new Set(),
  episodeGroupErrors: {},
  episodeGalleryPages: {},
  openEpisodeGroups: {},
  stagedEpisodes: new Set(),
  stagedPromptOverrides: new Map(),
  includedEpisodeSelection: new Set(),
  includedEpisodePages: {},
  jobs: [],
  activeJobId: null,
  jobPollTimer: null,
  currentPhase: 'sources',
};

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
}

async function apiJSON(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json') ? await response.json() : {};
  if (!response.ok) {
    const detail = payload.detail || payload.error;
    if (typeof detail === 'string') throw new Error(detail);
    if (detail && typeof detail === 'object') {
      const messages = (detail.errors || []).map((error) => error.message || String(error));
      throw new Error([detail.message, ...messages].filter(Boolean).join(' · ') || JSON.stringify(detail));
    }
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return payload;
}

function showPhase(phase) {
  state.currentPhase = phase;
  document.querySelectorAll('.phase-tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.phase === phase));
  document.querySelectorAll('.phase-panel').forEach((panel) => panel.classList.toggle('active', panel.id === phase));
  if (phase === 'output') renderOutputSettings();
  if (phase === 'tasks') renderTasksEditor();
  if (phase === 'cameras') renderCameraWorkspace();
  if (phase === 'joints') renderJointMapping();
  if (phase === 'balance' || phase === 'preflight') refreshPreflight();
  if (phase === 'export') {
    renderExportControls();
    if (!state.preflight || state.preflightStale) refreshPreflight();
    loadJobs();
  }
}

function updateBadges() {
  $('#badge-sources').textContent = state.catalog.length ? `${new Set(state.catalog.map((dataset) => dataset.name.split('/')[0])).size}` : '';
  $('#badge-episodes').textContent = state.choices.size || '';
  const mapped = Object.values(state.mappings).reduce((count, mapping) => count + Object.values(mapping).filter(Boolean).length, 0);
  $('#badge-cameras').textContent = mapped || '';
  const currentJointMap = state.jointMappings[state.currentDataset] || {};
  const mappedJoints = ['action', 'observation.state'].reduce(
    (count, feature) => count + Object.keys(currentJointMap[feature] || {}).length,
    0,
  );
  $('#badge-joints').textContent = mappedJoints === 12 ? 'ready' : mappedJoints ? `${mappedJoints}/12` : '';
  $('#badge-output').textContent = state.settingsLoaded ? 'set' : '';
  const retained = state.preflight ? Object.values(state.preflight.retained_task_counts || {}).reduce((sum, count) => sum + Number(count), 0) : 0;
  $('#badge-balance').textContent = retained || '';
  if (state.preflightStale) $('#badge-preflight').textContent = 'stale';
  else if (state.preflight) $('#badge-preflight').textContent = state.preflight.ok ? 'ready' : `${(state.preflight.errors || []).length} issues`;
  const active = state.jobs.filter((job) => ['queued', 'running', 'cancelling'].includes(job.status)).length;
  $('#badge-export').textContent = active ? `${active} active` : '';
}

function setSaveStatus(message, status = '') {
  $('#save-banner').textContent = message;
  $('#save-banner').className = `save-banner ${status}`;
}

function setSettingsStatus(message, kind = '') {
  const status = $('#settings-status');
  status.textContent = message;
  status.className = `hint inline-status ${kind}`;
}

function markPreflightStale(reason) {
  state.preflightStale = true;
  state.preflightReason = reason;
  $('#export-confirm').checked = false;
  updateBadges();
  renderPreflight();
  renderExportControls();
}

function requiredCameras() {
  return ['wrist', state.settings.second_camera];
}

function recipeForDataset(dataset) {
  return {
    choices: [...state.choices.values()].filter((choice) => choice.dataset_path === dataset.path),
    camera_mapping: state.mappings[dataset.path] || {},
    joint_mapping: state.jointMappings[dataset.path] || {},
    flags: state.datasetFlags[dataset.path] || [],
    flag_definitions: state.flags,
    required_cameras: requiredCameras(),
    max_per_task: state.settings.max_per_task,
  };
}

function hydrateDataset(dataset) {
  const recipe = state.sharedCheckpoints[dataset.path]?.recipe || {};
  state.choices = new Map((recipe.choices || []).map((choice) => [
    choice.key || `${dataset.path}:${choice.episode_index}`,
    { ...choice, key: choice.key || `${dataset.path}:${choice.episode_index}` },
  ]));
  state.mappings[dataset.path] = recipe.camera_mapping || {};
  state.jointMappings[dataset.path] = recipe.joint_mapping || {};
  state.datasetFlags[dataset.path] = recipe.flags || [];
  state.flags = recipe.flag_definitions || state.flags;
  state.stagedEpisodes.clear();
  state.stagedPromptOverrides.clear();
  state.includedEpisodeSelection.clear();
  state.includedEpisodePages[dataset.path] = 0;
  state.episodeGalleryPages[dataset.path] = 0;
  state.dirty = false;
  renderFlags();
  renderSummary();
  updateBadges();
}

async function loadWorkspace() {
  const result = await apiJSON(`/api/workspaces/${encodeURIComponent(state.user)}`);
  state.checkpoints = result.checkpoints || {};
}

function activeWorkspace() {
  return state.workspaceRegistry?.workspaces?.find((workspace) => workspace.id === state.workspaceRegistry.active_workspace_id) || null;
}

function selectedWorkspace() {
  return state.workspaceRegistry?.workspaces?.find((workspace) => workspace.id === state.selectedWorkspaceId) || null;
}

function renderWorkspaceControls() {
  const select = $('#workspace-select');
  const active = activeWorkspace();
  const workspaces = state.workspaceRegistry?.workspaces || [];
  $('#workspace-name').textContent = active?.name || 'Workspace unavailable';
  select.innerHTML = workspaces.map((workspace) => `<option value="${escapeHtml(workspace.id)}">${escapeHtml(workspace.name)}</option>`).join('');
  if (!workspaces.some((workspace) => workspace.id === state.selectedWorkspaceId)) state.selectedWorkspaceId = active?.id || null;
  select.value = state.selectedWorkspaceId || '';
  select.disabled = !active || state.workspaceTransitionPending;
  $('#new-workspace').disabled = !active || state.workspaceTransitionPending;
  $('#switch-workspace').disabled = !active
    || state.workspaceTransitionPending
    || state.selectedWorkspaceId === active.id;
}

async function loadWorkspaceRegistry() {
  state.workspaceRegistry = await apiJSON('/api/workspace-registry');
  state.selectedWorkspaceId = state.workspaceRegistry.active_workspace_id;
  renderWorkspaceControls();
}

function setWorkspaceDialogError(dialog, message = '') {
  dialog.querySelector('[data-workspace-error]').textContent = message;
}

function updateNewWorkspaceConfirmation() {
  const currentName = $('#new-workspace-current-name').value;
  const newName = $('#new-workspace-name').value;
  const confirmation = $('#new-workspace-confirmation').value;
  $('#start-new-workspace').disabled = state.workspaceTransitionPending || !(currentName.trim()
    && newName.trim()
    && confirmation === 'START NEW WORKSPACE');
}

function updateSwitchWorkspaceConfirmation() {
  const activeWorkspaceId = state.workspaceRegistry?.active_workspace_id;
  const confirmation = $('#switch-workspace-confirmation').value;
  $('#confirm-switch-workspace').disabled = state.workspaceTransitionPending || !(state.selectedWorkspaceId !== activeWorkspaceId
    && confirmation === 'SWITCH WORKSPACE');
}

function setWorkspaceTransitionPending(pending) {
  state.workspaceTransitionPending = pending;
  document.body.inert = pending;
  document.querySelectorAll('.workspace-dialog input, .workspace-dialog [data-dialog-cancel]').forEach((control) => {
    control.disabled = pending;
  });
  renderWorkspaceControls();
  updateNewWorkspaceConfirmation();
  updateSwitchWorkspaceConfirmation();
}

function openNewWorkspaceDialog() {
  const active = activeWorkspace();
  if (!active) return;
  const dialog = $('#new-workspace-dialog');
  $('#new-workspace-current-name').value = active.name;
  $('#new-workspace-name').value = '';
  $('#new-workspace-confirmation').value = '';
  setWorkspaceDialogError(dialog);
  updateNewWorkspaceConfirmation();
  dialog.showModal();
  $('#new-workspace-name').focus();
}

function openSwitchWorkspaceDialog() {
  const active = activeWorkspace();
  const destination = selectedWorkspace();
  if (!active || !destination || destination.id === active.id) return;
  const dialog = $('#switch-workspace-dialog');
  $('#switch-workspace-current-name').textContent = active.name;
  $('#switch-workspace-destination-name').textContent = destination.name;
  $('#switch-workspace-confirmation').value = '';
  setWorkspaceDialogError(dialog);
  updateSwitchWorkspaceConfirmation();
  dialog.showModal();
  $('#switch-workspace-confirmation').focus();
}

function completeWorkspaceTransition() {
  localStorage.removeItem('dataset-studio-user');
  setSaveStatus('Workspace saved. Loading the new workspace…', 'saved');
  window.setTimeout(() => window.location.reload(), 500);
}

async function flushWorkspaceAutosave(dialog) {
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  while (state.currentSave) {
    const inFlightSaved = await state.currentSave;
    if (!inFlightSaved) {
      setWorkspaceDialogError(dialog, 'Could not save the current workspace. Resolve the save error before continuing.');
      return false;
    }
  }
  const current = state.catalog.find((item) => item.path === state.currentDataset);
  if (current && state.dirty) {
    const saved = await persistCheckpoint(current, 'draft', false, true);
    if (!saved) {
      setWorkspaceDialogError(dialog, 'Could not save the current workspace. Resolve the save error before continuing.');
      return false;
    }
  }
  if (state.dirty) {
    setWorkspaceDialogError(dialog, 'Could not identify the dirty dataset to save. Reopen it before continuing.');
    return false;
  }
  return true;
}

function runWorkspaceTransition(dialog, request, failurePrefix) {
  if (state.workspaceTransitionPromise) return state.workspaceTransitionPromise;
  let succeeded = false;
  const transition = (async () => {
    setWorkspaceTransitionPending(true);
    setWorkspaceDialogError(dialog);
    try {
      if (!await flushWorkspaceAutosave(dialog)) return false;
      await request();
      succeeded = true;
      completeWorkspaceTransition();
      return true;
    } catch (error) {
      setWorkspaceDialogError(dialog, `${failurePrefix}: ${error.message}`);
      return false;
    } finally {
      if (!succeeded) setWorkspaceTransitionPending(false);
      if (!succeeded && state.workspaceTransitionPromise === transition) state.workspaceTransitionPromise = null;
    }
  })();
  state.workspaceTransitionPromise = transition;
  return transition;
}

function startNewWorkspace() {
  const currentName = $('#new-workspace-current-name').value.trim();
  const newName = $('#new-workspace-name').value.trim();
  const confirmation = $('#new-workspace-confirmation').value;
  if (!currentName || !newName || confirmation !== 'START NEW WORKSPACE') return Promise.resolve(false);
  const dialog = $('#new-workspace-dialog');
  return runWorkspaceTransition(
    dialog,
    () => apiJSON('/api/workspaces/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_name: currentName, new_name: newName, confirmation }),
    }),
    'Could not start workspace',
  );
}

function switchWorkspace() {
  const activeWorkspaceId = state.workspaceRegistry?.active_workspace_id;
  const destinationWorkspaceId = state.selectedWorkspaceId;
  const confirmation = $('#switch-workspace-confirmation').value;
  if (destinationWorkspaceId === activeWorkspaceId || confirmation !== 'SWITCH WORKSPACE') return Promise.resolve(false);
  const dialog = $('#switch-workspace-dialog');
  return runWorkspaceTransition(
    dialog,
    () => apiJSON('/api/workspaces/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: destinationWorkspaceId, confirmation }),
    }),
    'Could not switch workspace',
  );
}

async function loadClaims() {
  state.claims = (await apiJSON('/api/claims')).claims || {};
}

async function loadSharedCheckpoints() {
  state.sharedCheckpoints = (await apiJSON('/api/shared-checkpoints')).checkpoints || {};
}

async function loadSettings() {
  state.settings = { ...DEFAULT_SETTINGS, ...(await apiJSON('/api/settings')) };
  state.settingsLoaded = true;
  state.settings.required_cameras = requiredCameras();
  renderOutputSettings();
  renderCameraContract();
  updateBadges();
}

function cameraCandidates() {
  const candidates = new Set(['front', 'desk_view', 'top']);
  state.catalog.forEach((dataset) => (dataset.cameras || []).forEach((camera) => {
    const leaf = String(camera).split('.').at(-1);
    if (leaf && !leaf.toLowerCase().includes('wrist')) candidates.add(leaf);
  }));
  if (state.settings.second_camera) candidates.add(state.settings.second_camera);
  return [...candidates].filter((camera) => camera && camera !== 'wrist').sort((left, right) => left.localeCompare(right));
}

function fillCameraSelect(select, selected) {
  const candidates = cameraCandidates();
  if (selected && !candidates.includes(selected) && selected !== 'wrist') candidates.push(selected);
  select.innerHTML = candidates.sort((left, right) => left.localeCompare(right)).map((camera) => `<option value="${escapeHtml(camera)}">${escapeHtml(camera)}</option>`).join('');
  select.value = selected || candidates[0] || '';
}

function renderOutputSettings() {
  if (!state.settingsLoaded) return;
  $('#output-name').value = state.settings.output_name || '';
  $('#output-parent').value = state.settings.output_parent || '';
  $('#max-per-task').value = state.settings.max_per_task ?? '';
  fillCameraSelect($('#second-camera'), state.settings.second_camera);
  renderCameraContract();
}

function renderCameraContract() {
  const second = state.settings.second_camera || 'not set';
  $('#episode-second-camera').textContent = second;
  $('#camera-contract-mini').innerHTML = `<small>EXPORT CONTRACT</small><strong>wrist</strong><span>+</span><strong>${escapeHtml(second)}</strong>`;
  fillCameraSelect($('#export-second-camera'), $('#export-second-camera').value || second);
}

async function saveProjectSettings({ useExportCamera = false } = {}) {
  const previousSecond = state.settings.second_camera;
  const secondCamera = useExportCamera ? $('#export-second-camera').value : $('#second-camera').value;
  const payload = {
    output_name: $('#output-name').value.trim(),
    output_parent: $('#output-parent').value.trim(),
    second_camera: secondCamera,
    max_per_task: $('#max-per-task').value ? Number($('#max-per-task').value) : null,
  };
  setSettingsStatus('Saving project settings…', 'saving');
  try {
    state.settings = { ...DEFAULT_SETTINGS, ...(await apiJSON('/api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })) };
    state.settingsLoaded = true;
    setSettingsStatus('Project settings saved.', 'saved');
    if (previousSecond !== state.settings.second_camera) {
      $('#camera-change-notice').innerHTML = `<p class="notice bad"><strong>Camera contract changed.</strong> ${escapeHtml(previousSecond)} is no longer an export target. Revisit Cameras for every approved dataset and map exactly one source view to <strong>${escapeHtml(state.settings.second_camera)}</strong>, then rerun Preflight.</p>`;
    }
    markPreflightStale(previousSecond !== state.settings.second_camera
      ? `Second camera changed from ${previousSecond} to ${state.settings.second_camera}; approved datasets must be remapped.`
      : 'Project settings changed; rerun preflight to freeze a new manifest.');
    renderOutputSettings();
    renderCameraWorkspace();
    renderExportControls();
    return true;
  } catch (error) {
    setSettingsStatus(`Could not save: ${error.message}`, 'failed');
    return false;
  }
}

async function runWorkspaceMutation(operation, allowDuringWorkspaceTransition = false) {
  if (state.workspaceTransitionPending && !allowDuringWorkspaceTransition) return false;
  const previousMutation = state.currentSave;
  const mutation = (async () => {
    if (previousMutation) {
      const previousSucceeded = await previousMutation;
      if (!previousSucceeded) return false;
    }
    return operation();
  })();
  state.currentSave = mutation;
  try {
    return await mutation;
  } finally {
    if (state.currentSave === mutation) state.currentSave = null;
  }
}

async function saveCheckpointRequest(dataset, status = 'draft', refreshCatalog = false) {
  const saveVersion = state.dirtyVersion;
  setSaveStatus('Saving…', 'saving');
  try {
    const result = await apiJSON('/api/checkpoints', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: state.user, dataset_path: dataset.path, status, recipe: recipeForDataset(dataset) }),
    });
    state.checkpoints = result.checkpoints || state.checkpoints;
    if (result.shared_checkpoint) state.sharedCheckpoints[dataset.path] = result.shared_checkpoint;
    if (state.dirtyVersion === saveVersion) {
      state.dirty = false;
      setSaveStatus(`Changes saved · revision ${result.shared_checkpoint?.revision ?? '?'}`, 'saved');
    } else {
      setSaveStatus('Unsaved changes', 'saving');
    }
    markPreflightStale(`${dataset.name} checkpoint changed; refresh approved data.`);
    if (refreshCatalog) renderCatalog();
    return true;
  } catch (error) {
    setSaveStatus(`Save failed: ${error.message}`, 'failed');
    return false;
  }
}

function persistCheckpoint(
  dataset,
  status = 'draft',
  refreshCatalog = false,
  allowDuringWorkspaceTransition = false,
) {
  return runWorkspaceMutation(
    () => saveCheckpointRequest(dataset, status, refreshCatalog),
    allowDuringWorkspaceTransition,
  );
}

function scheduleAutosave(datasetPath = state.currentDataset) {
  if (state.workspaceTransitionPending) return;
  if (!datasetPath || state.claims[datasetPath] !== state.user) return;
  clearTimeout(state.saveTimer);
  state.dirty = true;
  state.dirtyVersion += 1;
  setSaveStatus('Unsaved changes', 'saving');
  state.saveTimer = setTimeout(() => {
    state.saveTimer = null;
    const dataset = state.catalog.find((item) => item.path === datasetPath);
    if (dataset) persistCheckpoint(dataset, 'draft');
  }, 500);
}

async function claimCurrentDataset(dataset) {
  return runWorkspaceMutation(async () => {
    try {
      await apiJSON('/api/claims', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: state.user, dataset_path: dataset.path, status: 'draft' }),
      });
      await Promise.all([loadClaims(), loadSharedCheckpoints()]);
      state.currentDataset = dataset.path;
      state.focusedEpisode = null;
      hydrateDataset(dataset);
      renderEpisodeBrowser();
      renderChoices();
      renderCameraWorkspace();
      showPhase('cameras');
      renderCatalog();
      return true;
    } catch (error) {
      alert(error.message);
      return false;
    }
  });
}

async function saveCheckpoint(dataset, status) {
  await persistCheckpoint(dataset, status, true);
}

async function excludeDataset(dataset) {
  const reason = window.prompt('Reason for excluding this dataset from export:', dataset.valid ? '' : (dataset.issues.join('; ') || 'quarantined source'));
  if (reason === null || !reason.trim()) return;
  return runWorkspaceMutation(async () => {
    try {
      if (!state.claims[dataset.path]) {
        await apiJSON('/api/claims', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ user: state.user, dataset_path: dataset.path, status: 'draft' }),
        });
      }
      const result = await apiJSON('/api/checkpoints', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user: state.user,
          dataset_path: dataset.path,
          status: 'excluded',
          recipe: { ...recipeForDataset(dataset), reason: reason.trim() },
        }),
      });
      if (result.shared_checkpoint) state.sharedCheckpoints[dataset.path] = result.shared_checkpoint;
      await apiJSON('/api/claims', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: state.user, dataset_path: dataset.path, status: 'excluded' }),
      });
      await Promise.all([loadWorkspace(), loadClaims(), loadSharedCheckpoints()]);
      if (state.currentDataset === dataset.path) state.currentDataset = null;
      setSaveStatus(`Dataset excluded · ${reason.trim()} · claim released`, 'saved');
      markPreflightStale(`${dataset.name} was excluded; refresh approved data.`);
      renderCatalog();
      return true;
    } catch (error) {
      setSaveStatus(`Exclude failed: ${error.message}`, 'failed');
      return false;
    }
  });
}

async function toggleCheckpointHistory(dataset, button) {
  const existing = button.closest('.dataset-card').querySelector('[data-history-view]');
  if (existing) {
    existing.remove();
    button.textContent = 'History';
    return;
  }
  button.disabled = true;
  try {
    const payload = await apiJSON(`/api/checkpoint-history?dataset_path=${encodeURIComponent(dataset.path)}`);
    const rows = payload.history || [];
    const html = rows.length
      ? `<ol>${[...rows].reverse().map((item) => `<li><b>r${item.revision} · ${escapeHtml(item.status)}</b><span>${escapeHtml(item.updated_by)} · ${escapeHtml(item.updated_at || '')}</span>${item.status === 'excluded' && item.recipe?.reason ? `<small>${escapeHtml(item.recipe.reason)}</small>` : ''}</li>`).join('')}</ol>`
      : '<p class="empty">No shared checkpoint revisions yet.</p>';
    button.closest('.flag-actions').insertAdjacentHTML('afterend', `<div class="checkpoint-history" data-history-view><small>SHARED REVISION HISTORY</small>${html}</div>`);
    button.textContent = 'Hide history';
  } catch (error) {
    setSaveStatus(`History failed: ${error.message}`, 'failed');
  } finally {
    button.disabled = false;
  }
}

async function releaseClaim(dataset) {
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  return runWorkspaceMutation(async () => {
    if (state.dirty && !await saveCheckpointRequest(dataset, 'draft')) return false;
    try {
      const result = await apiJSON('/api/claims', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: state.user, dataset_path: dataset.path, status: 'draft' }),
      });
      state.claims = result.claims || {};
      if (state.currentDataset === dataset.path) state.currentDataset = null;
      setSaveStatus('Claim released · saved changes retained', 'saved');
      renderCatalog();
      showPhase('sources');
      return true;
    } catch (error) {
      setSaveStatus(`Release failed: ${error.message}`, 'failed');
      return false;
    }
  });
}

async function releaseAllMyClaims() {
  clearTimeout(state.saveTimer);
  state.saveTimer = null;
  const current = state.catalog.find((item) => item.path === state.currentDataset);
  return runWorkspaceMutation(async () => {
    if (
      current
      && state.claims[current.path] === state.user
      && state.dirty
      && !await saveCheckpointRequest(current, 'draft')
    ) return false;
    try {
      const result = await apiJSON(`/api/claims/user/${encodeURIComponent(state.user)}`, { method: 'DELETE' });
      state.claims = result.claims || {};
      state.currentDataset = null;
      setSaveStatus('All claims released · saved changes retained', 'saved');
      renderCatalog();
      showPhase('sources');
      return true;
    } catch (error) {
      setSaveStatus(`Release failed: ${error.message}`, 'failed');
      return false;
    }
  });
}

function toggleDatasetFlag(datasetPath, flagIndex) {
  const flags = new Set(state.datasetFlags[datasetPath] || []);
  flags.has(flagIndex) ? flags.delete(flagIndex) : flags.add(flagIndex);
  state.datasetFlags[datasetPath] = [...flags];
  scheduleAutosave(datasetPath);
  renderCatalog();
}

function renderFlags() {
  $('#flag-list').innerHTML = state.flags.map((flag, index) => `<button class="quiet" data-flag-id="${index}">${escapeHtml(flag.name)} <small>Ctrl+${index + 1}</small></button>`).join('');
}

function renderMetrics(summary) {
  $('#metrics').innerHTML = [
    `<strong>${summary.datasets}</strong> datasets`,
    `<strong>${summary.valid}</strong> valid`,
    `<strong>${summary.usable_episodes}</strong> usable episodes`,
  ].map((item) => `<span>${item}</span>`).join('');
}

function renderChoices() {
  updateBadges();
}

function renderCameraWorkspace() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  const second = state.settings.second_camera;
  $('#camera-dataset').textContent = dataset ? `Map views for ${dataset.name}. Each preview uses one representative usable episode.` : 'Open a source in Sources first.';
  renderCameraContract();
  if (!dataset) {
    $('#camera-workspace').innerHTML = '<p class="empty">Claim and open one dataset to map its cameras.</p>';
    return;
  }
  state.mappings[dataset.path] ||= {};
  const sample = dataset.episodes.find((episode) => !episode.exclusion_reason && Object.keys(episode.video_files || {}).length) || dataset.episodes[0];
  $('#camera-workspace').innerHTML = dataset.cameras.map((camera) => {
    const query = sample ? new URLSearchParams({ dataset_path: dataset.path, episode_index: sample.index, camera }) : null;
    const start = sample?.video_starts?.[camera] || 0;
    const saved = state.mappings[dataset.path][camera];
    const invalid = saved && !['wrist', second].includes(saved);
    return `<article class="choice camera-choice">
      <div><h3>${escapeHtml(camera)}</h3><p>Representative episode ${sample?.index ?? 'unavailable'}</p></div>
      ${query ? `<button class="quiet preview-button" data-camera-preview="/api/preview?${query}#t=${start}">Load preview</button><div class="preview-target"></div>` : ''}
      ${invalid ? `<p class="map-warning">Previous target “${escapeHtml(saved)}” is no longer in the output contract. Map this view again.</p>` : ''}
      <label>Map source view to
        <select data-camera-map="${escapeHtml(camera)}">
          <option value="">Omit</option>
          <option value="wrist">wrist</option>
          <option value="${escapeHtml(second)}">${escapeHtml(second)}</option>
        </select>
      </label>
    </article>`;
  }).join('');
  $('#camera-workspace').querySelectorAll('[data-camera-map]').forEach((select) => {
    const saved = state.mappings[dataset.path][select.dataset.cameraMap] || '';
    select.value = ['wrist', second].includes(saved) ? saved : '';
    select.onchange = () => {
      state.mappings[dataset.path][select.dataset.cameraMap] = select.value || null;
      updateBadges();
      scheduleAutosave(dataset.path);
    };
  });
  $('#camera-workspace').querySelectorAll('[data-camera-preview]').forEach((button) => {
    button.onclick = () => {
      button.nextElementSibling.innerHTML = `<video controls autoplay preload="metadata" src="${button.dataset.cameraPreview}"></video>`;
      button.remove();
    };
  });
}

function cloneMapping(mapping) {
  return JSON.parse(JSON.stringify(mapping || {}));
}

function jointMappingComplete(mapping, canonicalJoints) {
  return ['action', 'observation.state'].every((feature) => {
    const values = canonicalJoints.map((joint) => mapping?.[feature]?.[joint]);
    return values.every((value) => Number.isInteger(value))
      && new Set(values).size === canonicalJoints.length;
  });
}

function jointOptions(names, selected) {
  return `<option value="">Choose source position…</option>${names.map(
    (name, index) => `<option value="${index}" ${selected === index ? 'selected' : ''}>${index} · ${escapeHtml(name)}</option>`,
  ).join('')}`;
}

async function renderJointMapping() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  $('#joint-dataset').textContent = dataset
    ? `Mapping action and observation.state for ${dataset.name}.`
    : 'Open a source in Sources first.';
  if (!dataset) {
    $('#joint-status').textContent = 'Not loaded';
    $('#joint-status').className = 'schema-stamp';
    $('#joint-workspace').innerHTML = '<p class="empty">Claim and open one dataset to map its six robot joints.</p>';
    return;
  }

  $('#joint-status').textContent = 'Reading schema…';
  $('#joint-status').className = 'schema-stamp';
  $('#joint-workspace').innerHTML = '<p class="notice">Reading action and observation.state names…</p>';
  try {
    const contract = state.jointContracts[dataset.path] || await apiJSON(
      `/api/datasets/joint-contract?dataset_path=${encodeURIComponent(dataset.path)}`,
    );
    state.jointContracts[dataset.path] = contract;
    const canonical = contract.canonical_joints || [];
    const mapping = state.jointMappings[dataset.path] ||= {};
    let proposed = false;
    for (const feature of ['action', 'observation.state']) {
      if (!mapping[feature] || !Object.keys(mapping[feature]).length) {
        mapping[feature] = cloneMapping(contract.proposal?.[feature] || {});
        proposed = proposed || Object.keys(mapping[feature]).length > 0;
      }
    }
    if (proposed) scheduleAutosave(dataset.path);

    const structurallyBlocked = (contract.errors || []).filter((error) => !error.includes('could not be mapped automatically'));
    const complete = jointMappingComplete(mapping, canonical);
    $('#joint-status').textContent = structurallyBlocked.length ? 'Incompatible' : complete ? '6 + 6 mapped' : 'Needs review';
    $('#joint-status').className = `schema-stamp ${structurallyBlocked.length ? 'blocked' : complete ? 'ready' : ''}`;
    const errors = structurallyBlocked.length
      ? `<div class="notice bad"><strong>This dataset cannot be approved.</strong><ul>${structurallyBlocked.map((error) => `<li>${escapeHtml(error)}</li>`).join('')}</ul></div>`
      : !complete
        ? '<p class="notice">Automatic matching was incomplete. Assign every canonical joint once in each source vector.</p>'
        : '<p class="notice good">Both vectors map cleanly to the canonical six-joint order.</p>';
    const rows = canonical.map((joint) => `<div class="joint-row">
      <strong>${escapeHtml(joint)}</strong>
      <label><small>ACTION SOURCE</small><select data-joint-feature="action" data-joint-name="${escapeHtml(joint)}">${jointOptions(contract.action_names || [], mapping.action?.[joint])}</select></label>
      <label><small>STATE SOURCE</small><select data-joint-feature="observation.state" data-joint-name="${escapeHtml(joint)}">${jointOptions(contract.state_names || [], mapping['observation.state']?.[joint])}</select></label>
    </div>`).join('');
    $('#joint-workspace').innerHTML = `${errors}<div class="joint-grid">
      <div class="joint-row joint-head"><span>Canonical output</span><span>action</span><span>observation.state</span></div>
      ${rows}
    </div>`;
    $('#joint-workspace').querySelectorAll('[data-joint-feature]').forEach((select) => {
      select.onchange = () => {
        const feature = select.dataset.jointFeature;
        const joint = select.dataset.jointName;
        state.jointMappings[dataset.path][feature] ||= {};
        if (select.value === '') delete state.jointMappings[dataset.path][feature][joint];
        else state.jointMappings[dataset.path][feature][joint] = Number(select.value);
        const nowComplete = jointMappingComplete(state.jointMappings[dataset.path], canonical);
        $('#joint-status').textContent = structurallyBlocked.length ? 'Incompatible' : nowComplete ? '6 + 6 mapped' : 'Needs review';
        $('#joint-status').className = `schema-stamp ${structurallyBlocked.length ? 'blocked' : nowComplete ? 'ready' : ''}`;
        markPreflightStale(`${dataset.name} joint mapping changed; rerun preflight.`);
        updateBadges();
        scheduleAutosave(dataset.path);
      };
    });
    updateBadges();
  } catch (error) {
    $('#joint-status').textContent = 'Could not load';
    $('#joint-status').className = 'schema-stamp blocked';
    $('#joint-workspace').innerHTML = `<p class="notice bad">Joint schema failed to load: ${escapeHtml(error.message)}</p>`;
  }
}

function renderSummary() {
  const counts = {};
  state.choices.forEach((choice) => {
    const task = choice.final_prompt.trim() || '(empty prompt)';
    counts[task] = (counts[task] || 0) + 1;
  });
  $('#summary').innerHTML = Object.keys(counts).length
    ? Object.entries(counts).sort().map(([task, count]) => `<div><span>${escapeHtml(task)}</span><b>${count}</b></div>`).join('')
    : '<p class="empty">Task counts will appear here.</p>';
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  const stagedCount = stagedEpisodesForDataset(dataset).length;
  $('#episode-selection-stats').innerHTML = `<span><strong>${state.choices.size}</strong> included episodes</span><span><strong>${stagedCount}</strong> staged episodes</span><span><strong>${Object.keys(counts).length}</strong> edited tasks</span>`;
  if (state.currentPhase === 'tasks') renderTasksEditor();
}

function episodeKey(dataset, episodeIndex) {
  return `${dataset.path}:${episodeIndex}`;
}

function stagedEpisodesForDataset(dataset) {
  if (!dataset) return [];
  return dataset.episodes.filter((episode) => state.stagedEpisodes.has(episodeKey(dataset, episode.index)));
}

function stagedPrompt(dataset, episode) {
  const key = episodeKey(dataset, episode.index);
  const selected = state.choices.get(key);
  const task = dataset.tasks.find((item) => item.index === episode.task_index);
  return state.stagedPromptOverrides.get(key) ?? selected?.final_prompt ?? task?.prompt ?? '';
}

function stageEpisode(dataset, episode) {
  if (!dataset.valid || episode.exclusion_reason) return false;
  state.stagedEpisodes.add(episodeKey(dataset, episode.index));
  return true;
}

function unstageEpisode(dataset, episodeIndex) {
  const key = episodeKey(dataset, episodeIndex);
  state.stagedEpisodes.delete(key);
  state.stagedPromptOverrides.delete(key);
}

function updateStagingControls(dataset = state.catalog.find((item) => item.path === state.currentDataset)) {
  const staged = stagedEpisodesForDataset(dataset);
  const count = staged.length;
  $('#bulk-task-selection').textContent = `${count} staged episode${count === 1 ? '' : 's'}`;
  $('#apply-bulk-task-prompt').disabled = count === 0 || !$('#bulk-task-prompt').value.trim();
  $('#include-staged-episodes').disabled = count === 0;
  $('#unselect-staged-episodes').disabled = count === 0
    || !staged.some((episode) => state.choices.has(episodeKey(dataset, episode.index)));
  $('#clear-staged-episodes').disabled = count === 0;
  return count;
}

function setBulkTaskStatus(message, kind = '') {
  $('#bulk-task-status').innerHTML = message
    ? `<p class="notice ${kind}">${escapeHtml(message)}</p>`
    : '';
}

function renderTasksEditor() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  const view = $('#tasks-view');
  if (!dataset) {
    view.innerHTML = '<p class="empty">Open a dataset and stage episodes before using the staging tray.</p>';
    updateStagingControls(null);
    renderIncludedEpisodes(null);
    return;
  }
  const staged = stagedEpisodesForDataset(dataset);
  if (!staged.length) {
    view.innerHTML = '<p class="empty">Nothing is staged. Stage episodes from the gallery, page controls, or Subtask groups first.</p>';
    updateStagingControls(dataset);
    renderIncludedEpisodes(dataset);
    return;
  }
  view.innerHTML = staged.map((episode) => {
    const key = episodeKey(dataset, episode.index);
    const task = dataset.tasks.find((item) => item.index === episode.task_index);
    const included = state.choices.has(key);
    return `<article class="task-bulk-row ${included ? 'included' : ''}">
      <span>
        <strong>Episode ${episode.index} · ${episode.duration_seconds.toFixed(1)}s</strong>
        <small>Task ${episode.task_index} · ${escapeHtml(task?.prompt || 'Untitled')}</small>
        <small>Staged final: ${escapeHtml(stagedPrompt(dataset, episode))}</small>
      </span>
      <span class="stage-state ${included ? 'included' : ''}">${included ? 'Included' : 'Not included'}</span>
      <div class="stage-row-actions">
        <button type="button" data-include-staged-one="${episode.index}" ${included ? 'disabled' : ''}>Include</button>
        <button type="button" class="quiet danger" data-exclude-staged-one="${episode.index}" ${included ? '' : 'disabled'}>Exclude</button>
        <button type="button" class="quiet" data-remove-staged="${episode.index}" aria-label="Remove episode ${episode.index} from stage">Unstage</button>
      </div>
    </article>`;
  }).join('');
  view.querySelectorAll('[data-include-staged-one]').forEach((button) => {
    button.onclick = () => commitOneStagedEpisode(
      dataset,
      Number(button.dataset.includeStagedOne),
      true,
    );
  });
  view.querySelectorAll('[data-exclude-staged-one]').forEach((button) => {
    button.onclick = () => commitOneStagedEpisode(
      dataset,
      Number(button.dataset.excludeStagedOne),
      false,
    );
  });
  view.querySelectorAll('[data-remove-staged]').forEach((button) => {
    button.onclick = () => {
      unstageEpisode(dataset, Number(button.dataset.removeStaged));
      renderTasksEditor();
      renderEpisodeBrowser();
      setBulkTaskStatus('Removed one episode from the temporary stage.');
    };
  });
  updateStagingControls(dataset);
  renderIncludedEpisodes(dataset);
}

function includedEpisodesForDataset(dataset) {
  if (!dataset) return [];
  const episodeByIndex = new Map(dataset.episodes.map((episode) => [episode.index, episode]));
  const taskByIndex = new Map(dataset.tasks.map((task) => [task.index, task]));
  return [...state.choices.values()]
    .filter((choice) => choice.dataset_path === dataset.path)
    .map((choice) => {
      const episode = episodeByIndex.get(choice.episode_index);
      return {
        choice,
        episode,
        task: episode ? taskByIndex.get(episode.task_index) : null,
      };
    })
    .sort((left, right) => left.choice.episode_index - right.choice.episode_index);
}

function renderIncludedEpisodes(dataset) {
  const view = $('#included-episodes-view');
  const controls = $('#included-page-controls');
  if (!dataset) {
    $('#included-episode-count').textContent = '0 included episodes';
    $('#included-bulk-selection').textContent = '0 checked';
    view.innerHTML = '<p class="empty">Open a dataset to review its included episodes.</p>';
    controls.innerHTML = '';
    $('#check-included-page').disabled = true;
    $('#clear-included-checks').disabled = true;
    $('#exclude-checked-included').disabled = true;
    $('#clear-all-included').disabled = true;
    return;
  }
  const included = includedEpisodesForDataset(dataset);
  const includedKeys = new Set(included.map(({ choice }) => choice.key));
  [...state.includedEpisodeSelection].forEach((key) => {
    if (!includedKeys.has(key)) state.includedEpisodeSelection.delete(key);
  });
  const totalPages = Math.max(1, Math.ceil(included.length / INCLUDED_EPISODE_PAGE_SIZE));
  const page = Math.max(0, Math.min(
    totalPages - 1,
    Number(state.includedEpisodePages[dataset.path]) || 0,
  ));
  state.includedEpisodePages[dataset.path] = page;
  const pageStart = page * INCLUDED_EPISODE_PAGE_SIZE;
  const pageItems = included.slice(pageStart, pageStart + INCLUDED_EPISODE_PAGE_SIZE);
  const checkedCount = [...state.includedEpisodeSelection].filter((key) => includedKeys.has(key)).length;
  const allPageChecked = pageItems.length > 0
    && pageItems.every(({ choice }) => state.includedEpisodeSelection.has(choice.key));
  $('#included-episode-count').textContent = `${included.length} included episode${included.length === 1 ? '' : 's'}`;
  $('#included-bulk-selection').textContent = `${checkedCount} checked`;
  $('#check-included-page').disabled = pageItems.length === 0 || allPageChecked;
  $('#clear-included-checks').disabled = checkedCount === 0;
  $('#exclude-checked-included').disabled = checkedCount === 0;
  $('#clear-all-included').disabled = included.length === 0;
  controls.innerHTML = included.length
    ? `<button type="button" class="quiet" data-included-previous ${page === 0 ? 'disabled' : ''}>←</button><span>Page ${page + 1} of ${totalPages}<small>${pageStart + 1}–${Math.min(pageStart + pageItems.length, included.length)} of ${included.length}</small></span><button type="button" class="quiet" data-included-next ${page >= totalPages - 1 ? 'disabled' : ''}>→</button>`
    : '';
  if (!included.length) {
    view.innerHTML = '<p class="empty">No episodes are currently included in this dataset.</p>';
    return;
  }
  controls.querySelector('[data-included-previous]').onclick = () => {
    state.includedEpisodePages[dataset.path] = page - 1;
    renderIncludedEpisodes(dataset);
  };
  controls.querySelector('[data-included-next]').onclick = () => {
    state.includedEpisodePages[dataset.path] = page + 1;
    renderIncludedEpisodes(dataset);
  };
  view.innerHTML = pageItems.map(({ choice, episode, task }) => {
    const checked = state.includedEpisodeSelection.has(choice.key);
    return `<article class="included-episode-row ${checked ? 'bulk-marked' : ''}">
      <label class="included-bulk-check" title="Mark episode ${choice.episode_index} for bulk exclusion">
        <input type="checkbox" data-included-bulk-select="${choice.episode_index}" ${checked ? 'checked' : ''}>
        <span class="sr-only">Mark included episode ${choice.episode_index}</span>
      </label>
      <span>
        <strong>Episode ${choice.episode_index}${episode ? ` · ${episode.duration_seconds.toFixed(1)}s` : ''}</strong>
        <small>Task ${episode?.task_index ?? 'unknown'} · ${escapeHtml(task?.prompt || 'Untitled')}</small>
        <small>Final prompt: ${escapeHtml(choice.final_prompt)}</small>
      </span>
      <button type="button" class="quiet danger" data-exclude-included-one="${choice.episode_index}">Exclude</button>
    </article>`;
  }).join('');
  view.querySelectorAll('[data-included-bulk-select]').forEach((checkbox) => {
    checkbox.onchange = () => {
      const key = episodeKey(dataset, Number(checkbox.dataset.includedBulkSelect));
      if (checkbox.checked) state.includedEpisodeSelection.add(key);
      else state.includedEpisodeSelection.delete(key);
      renderIncludedEpisodes(dataset);
    };
  });
  view.querySelectorAll('[data-exclude-included-one]').forEach((button) => {
    button.onclick = () => excludeIncludedEpisode(
      dataset,
      Number(button.dataset.excludeIncludedOne),
    );
  });
}

function applyBulkTaskPrompt() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  const replacement = $('#bulk-task-prompt').value.trim();
  const staged = stagedEpisodesForDataset(dataset);
  if (!dataset || !replacement || !staged.length) {
    setBulkTaskStatus('Stage at least one episode and enter a replacement prompt.', 'bad');
    return;
  }
  staged.forEach((episode) => {
    state.stagedPromptOverrides.set(episodeKey(dataset, episode.index), replacement);
  });
  $('#bulk-task-prompt').value = '';
  renderTasksEditor();
  renderEpisodeBrowser();
  setBulkTaskStatus(
    `Prepared “${replacement}” for ${staged.length} staged episode${staged.length === 1 ? '' : 's'}. Include one row or include all staged episodes to save it.`,
    'good',
  );
}

function applyStagedEpisodeToRecipe(dataset, episode, include) {
  const key = episodeKey(dataset, episode.index);
  if (include) {
    const prompt = stagedPrompt(dataset, episode).trim();
    const previous = state.choices.get(key);
    addChoice(dataset, episode, false);
    const choice = state.choices.get(key);
    const changed = !previous || (prompt && choice?.final_prompt !== prompt);
    if (choice && prompt) choice.final_prompt = prompt;
    return changed;
  }
  return state.choices.delete(key);
}

function commitOneStagedEpisode(dataset, episodeIndex, include) {
  const episode = dataset?.episodes.find((item) => item.index === episodeIndex);
  if (!episode || !state.stagedEpisodes.has(episodeKey(dataset, episodeIndex))) return;
  const changed = applyStagedEpisodeToRecipe(dataset, episode, include);
  if (!changed) return;
  finishEpisodeSelection(
    dataset,
    include
      ? `Included staged episode ${episode.index} in the recipe.`
      : `Excluded staged episode ${episode.index} from the recipe.`,
  );
  setBulkTaskStatus(
    include
      ? `Episode ${episode.index} is now included in the real recipe.`
      : `Episode ${episode.index} is now excluded from the real recipe.`,
    'good',
  );
}

function commitStagedEpisodes(include) {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  const staged = stagedEpisodesForDataset(dataset);
  if (!dataset || !staged.length) return;
  const changed = staged.reduce(
    (count, episode) => count + Number(applyStagedEpisodeToRecipe(dataset, episode, include)),
    0,
  );
  if (!changed) return;
  finishEpisodeSelection(
    dataset,
    include
      ? `Included ${changed} staged episode${changed === 1 ? '' : 's'} in the recipe.`
      : `Excluded ${changed} staged episode${changed === 1 ? '' : 's'} from the recipe.`,
  );
  setBulkTaskStatus(
    include
      ? `Saved ${changed} staged episode${changed === 1 ? '' : 's'} to the real recipe.`
      : `Excluded ${changed} staged episode${changed === 1 ? '' : 's'} from the real recipe.`,
    'good',
  );
}

function excludeCheckedIncludedEpisodes() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  if (!dataset) return;
  const checkedKeys = [...state.includedEpisodeSelection].filter((key) => state.choices.has(key));
  if (!checkedKeys.length) return;
  checkedKeys.forEach((key) => state.choices.delete(key));
  state.includedEpisodeSelection.clear();
  finishEpisodeSelection(
    dataset,
    `Excluded ${checkedKeys.length} checked episode${checkedKeys.length === 1 ? '' : 's'} from the recipe.`,
  );
  setBulkTaskStatus(
    `Excluded ${checkedKeys.length} checked included episode${checkedKeys.length === 1 ? '' : 's'}. The stage was preserved.`,
    'good',
  );
}

function excludeIncludedEpisode(dataset, episodeIndex) {
  const key = episodeKey(dataset, episodeIndex);
  if (!state.choices.delete(key)) return;
  state.includedEpisodeSelection.delete(key);
  finishEpisodeSelection(dataset, `Excluded included episode ${episodeIndex} from the recipe.`);
  setBulkTaskStatus(
    `Episode ${episodeIndex} was removed from the included list. The stage was preserved.`,
    'good',
  );
}

function clearAllIncludedEpisodes() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  if (!dataset) return;
  const includedKeys = [...state.choices.entries()]
    .filter(([, choice]) => choice.dataset_path === dataset.path)
    .map(([key]) => key);
  if (!includedKeys.length) return;
  const confirmed = window.confirm(
    `Clear all ${includedKeys.length} included episodes from ${dataset.name}? The temporary stage will be preserved.`,
  );
  if (!confirmed) return;
  includedKeys.forEach((key) => state.choices.delete(key));
  state.includedEpisodeSelection.clear();
  finishEpisodeSelection(dataset, `Cleared all ${includedKeys.length} included episodes from the recipe.`);
  setBulkTaskStatus(
    `Cleared all ${includedKeys.length} included episodes. The temporary stage was preserved.`,
    'good',
  );
}

function clearStagedEpisodes() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  if (!dataset) return;
  stagedEpisodesForDataset(dataset).forEach((episode) => unstageEpisode(dataset, episode.index));
  renderTasksEditor();
  renderEpisodeBrowser();
  setBulkTaskStatus('Cleared the temporary stage. The saved recipe was not changed.');
}

function addChoice(dataset, episode, shouldRender = true) {
  const key = `${dataset.path}:${episode.index}`;
  if (state.choices.has(key)) return;
  const task = dataset.tasks.find((item) => item.index === episode.task_index);
  state.choices.set(key, {
    key,
    dataset_path: dataset.path,
    datasetName: dataset.name,
    episode_index: episode.index,
    duration_seconds: episode.duration_seconds,
    final_prompt: task?.prompt || '',
  });
  if (shouldRender) renderSummary();
}

function setEpisodeGroupStatus(message, kind = '') {
  $('#episode-group-status').innerHTML = message
    ? `<p class="notice ${kind}">${escapeHtml(message)}</p>`
    : '';
}

function episodeGroupLabel(cluster) {
  const action = cluster.signature?.action || 'task';
  const relation = String(cluster.signature?.relation || 'general').replaceAll('_', ' ');
  return `${action.charAt(0).toUpperCase()}${action.slice(1)} · ${relation}`;
}

function selectedEpisodeCount(dataset, episodeIndices) {
  return episodeIndices.reduce(
    (count, episodeIndex) => count + Number(state.choices.has(`${dataset.path}:${episodeIndex}`)),
    0,
  );
}

function stagedEpisodeCount(dataset, episodeIndices) {
  return episodeIndices.reduce(
    (count, episodeIndex) => count + Number(state.stagedEpisodes.has(episodeKey(dataset, episodeIndex))),
    0,
  );
}

function unincludedEpisodeIndices(dataset, episodeIndices) {
  return (episodeIndices || []).filter(
    (episodeIndex) => !state.choices.has(episodeKey(dataset, episodeIndex)),
  );
}

function deterministicSpread(episodeIndices, requestedCount) {
  const indices = [...episodeIndices].sort((left, right) => left - right);
  const count = Math.max(0, Math.min(indices.length, Math.round(Number(requestedCount) || 0)));
  if (count === 0) return [];
  if (count >= indices.length) return indices;
  if (count === 1) return [indices[Math.floor((indices.length - 1) / 2)]];
  return Array.from(
    { length: count },
    (_, index) => indices[Math.round(index * (indices.length - 1) / (count - 1))],
  );
}

function setVariantStage(dataset, prompt, requestedCount) {
  const candidates = unincludedEpisodeIndices(dataset, prompt.episode_indices);
  const desired = new Set(deterministicSpread(candidates, requestedCount));
  candidates.forEach((episodeIndex) => {
    if (desired.has(episodeIndex)) {
      const episode = dataset.episodes.find((item) => item.index === episodeIndex);
      if (episode) stageEpisode(dataset, episode);
    } else {
      unstageEpisode(dataset, episodeIndex);
    }
  });
  return desired.size;
}

function finishEpisodeStage(dataset, message) {
  const scrollTop = $('#episode-gallery').scrollTop;
  renderEpisodeBrowser();
  $('#episode-gallery').scrollTop = scrollTop;
  renderSummary();
  setEpisodeGroupStatus(message, 'good');
}

function finishEpisodeSelection(dataset, message) {
  const scrollTop = $('#episode-gallery').scrollTop;
  renderEpisodeBrowser();
  $('#episode-gallery').scrollTop = scrollTop;
  renderSummary();
  updateBadges();
  markPreflightStale(`${dataset.name} episode selection changed; approve a new checkpoint before export.`);
  scheduleAutosave(dataset.path);
  setEpisodeGroupStatus(message, 'good');
}

function applyVariantTarget(dataset, clusterIndex, promptIndex, requestedCount) {
  const prompt = state.episodeGroups[dataset.path]?.clusters?.[clusterIndex]?.prompts?.[promptIndex];
  if (!prompt || !dataset.valid) return;
  const staged = setVariantStage(dataset, prompt, requestedCount);
  finishEpisodeStage(
    dataset,
    `Staged ${staged} new candidate${staged === 1 ? '' : 's'} for “${prompt.text}”; already-included episodes were left out.`,
  );
}

function applyGroupVariantTarget(dataset, clusterIndex, requestedCount) {
  const cluster = state.episodeGroups[dataset.path]?.clusters?.[clusterIndex];
  if (!cluster || !dataset.valid) return;
  let staged = 0;
  cluster.prompts.forEach((prompt) => {
    staged += setVariantStage(dataset, prompt, Math.min(requestedCount, prompt.available));
  });
  finishEpisodeStage(
    dataset,
    `Staged ${staged} new candidates across ${cluster.prompts.length} variants in ${episodeGroupLabel(cluster)}; already-included episodes were left out.`,
  );
}

function balancedClusterSelection(dataset, cluster, requestedCount) {
  const candidateLists = cluster.prompts.map(
    (prompt) => unincludedEpisodeIndices(dataset, prompt.episode_indices),
  );
  const candidateCount = candidateLists.reduce((count, indices) => count + indices.length, 0);
  const cap = Math.max(0, Math.min(candidateCount, Math.round(Number(requestedCount) || 0)));
  const allocations = cluster.prompts.map(() => 0);
  let remaining = cap;
  while (remaining > 0) {
    let allocated = false;
    candidateLists.forEach((indices, index) => {
      if (remaining > 0 && allocations[index] < indices.length) {
        allocations[index] += 1;
        remaining -= 1;
        allocated = true;
      }
    });
    if (!allocated) break;
  }
  return new Set(candidateLists.flatMap(
    (indices, index) => deterministicSpread(indices, allocations[index]),
  ));
}

function applyClusterCap(dataset, clusterIndex, requestedCount) {
  const cluster = state.episodeGroups[dataset.path]?.clusters?.[clusterIndex];
  if (!cluster || !dataset.valid) return;
  const desired = balancedClusterSelection(dataset, cluster, requestedCount);
  cluster.prompts.forEach((prompt) => {
    unincludedEpisodeIndices(dataset, prompt.episode_indices).forEach((episodeIndex) => {
      if (desired.has(episodeIndex)) {
        const episode = dataset.episodes.find((item) => item.index === episodeIndex);
        if (episode) stageEpisode(dataset, episode);
      } else {
        unstageEpisode(dataset, episodeIndex);
      }
    });
  });
  finishEpisodeStage(
    dataset,
    `Capped ${episodeGroupLabel(cluster)} at ${desired.size} new staged candidate${desired.size === 1 ? '' : 's'}, spread across its variants without reusing included episodes.`,
  );
}

async function loadEpisodeGroups(dataset) {
  if (!dataset || state.episodeGroupsLoading.has(dataset.path)) return;
  state.episodeGroupsLoading.add(dataset.path);
  delete state.episodeGroupErrors[dataset.path];
  renderEpisodeGroups(dataset);
  try {
    state.episodeGroups[dataset.path] = await apiJSON(
      `/api/datasets/episode-groups?${new URLSearchParams({ dataset_path: dataset.path })}`,
    );
  } catch (error) {
    state.episodeGroupErrors[dataset.path] = error.message;
  } finally {
    state.episodeGroupsLoading.delete(dataset.path);
    if (state.currentDataset === dataset.path) renderEpisodeGroups(dataset);
  }
}

function renderEpisodeVariantRows(dataset, clusterIndex, container) {
  const cluster = state.episodeGroups[dataset.path]?.clusters?.[clusterIndex];
  if (!cluster || container.dataset.rendered === 'true') return;
  const disabled = !dataset.valid;
  container.innerHTML = cluster.prompts.map((prompt, promptIndex) => {
    const candidates = unincludedEpisodeIndices(dataset, prompt.episode_indices);
    const promptSelected = selectedEpisodeCount(dataset, prompt.episode_indices);
    const promptStaged = stagedEpisodeCount(dataset, candidates);
    return `<div class="episode-variant-row">
      <div><strong>${escapeHtml(prompt.text)}</strong><small>${promptStaged} new staged · ${promptSelected} included · ${candidates.length} candidates left</small></div>
      <label>New candidates
        <input data-variant-target type="number" min="0" max="${candidates.length}" step="1" value="${promptStaged}" ${disabled ? 'disabled' : ''}>
      </label>
      <button type="button" class="quiet" data-apply-variant data-cluster-index="${clusterIndex}" data-prompt-index="${promptIndex}" ${disabled ? 'disabled' : ''}>Stage</button>
    </div>`;
  }).join('');
  container.dataset.rendered = 'true';
  container.querySelectorAll('[data-apply-variant]').forEach((button) => {
    button.onclick = () => {
      const row = button.closest('.episode-variant-row');
      applyVariantTarget(
        dataset,
        Number(button.dataset.clusterIndex),
        Number(button.dataset.promptIndex),
        Number(row.querySelector('[data-variant-target]').value),
      );
    };
  });
}

function renderEpisodeGroups(dataset) {
  const view = $('#episode-group-view');
  if (!dataset) {
    view.innerHTML = '<p class="empty">Open a dataset to group its usable episode prompts.</p>';
    setEpisodeGroupStatus('');
    return;
  }
  if (state.episodeGroupErrors[dataset.path]) {
    view.innerHTML = '';
    setEpisodeGroupStatus(`Could not group this dataset: ${state.episodeGroupErrors[dataset.path]}`, 'bad');
    return;
  }
  const data = state.episodeGroups[dataset.path];
  if (!data) {
    view.innerHTML = '<p class="empty">Building deterministic prompt groups…</p>';
    setEpisodeGroupStatus('Reading source prompts. Dataset files remain unchanged.');
    if (!state.episodeGroupsLoading.has(dataset.path)) loadEpisodeGroups(dataset);
    return;
  }
  if (!data.clusters.length) {
    view.innerHTML = '<p class="empty">No usable prompt variants are available in this dataset.</p>';
    setEpisodeGroupStatus('');
    return;
  }

  const disabled = !dataset.valid;
  state.openEpisodeGroups[dataset.path] ||= new Set();
  const openGroups = state.openEpisodeGroups[dataset.path];
  view.innerHTML = data.clusters.map((cluster, clusterIndex) => {
    const included = cluster.prompts.reduce(
      (count, prompt) => count + selectedEpisodeCount(dataset, prompt.episode_indices),
      0,
    );
    const candidateLists = cluster.prompts.map(
      (prompt) => unincludedEpisodeIndices(dataset, prompt.episode_indices),
    );
    const candidates = candidateLists.reduce((count, indices) => count + indices.length, 0);
    const staged = candidateLists.reduce(
      (count, indices) => count + stagedEpisodeCount(dataset, indices),
      0,
    );
    const groupMaximum = Math.max(...candidateLists.map((indices) => indices.length));
    return `<article class="episode-group-card">
      <header>
        <div><span class="group-state">Local cluster</span><h4>${escapeHtml(episodeGroupLabel(cluster))}</h4></div>
        <dl><div><dt>New staged</dt><dd>${staged}</dd></div><div><dt>Included</dt><dd>${included}</dd></div><div><dt>Candidates</dt><dd>${candidates}</dd></div><div><dt>Variants</dt><dd>${cluster.prompts.length}</dd></div></dl>
      </header>
      <div class="episode-group-bulk">
        <label>New per variant
          <input data-group-variant-target type="number" min="0" max="${groupMaximum}" step="1" placeholder="Count" ${disabled ? 'disabled' : ''}>
        </label>
        <button type="button" data-apply-group-target data-cluster-index="${clusterIndex}" ${disabled ? 'disabled' : ''}>Stage new per variant</button>
        <label>Cap new candidates at
          <input data-group-total-cap type="number" min="0" max="${candidates}" step="1" value="${staged}" ${disabled ? 'disabled' : ''}>
        </label>
        <button type="button" class="quiet" data-apply-group-cap data-cluster-index="${clusterIndex}" ${disabled ? 'disabled' : ''}>Stage new total</button>
      </div>
      <details data-episode-variants data-cluster-index="${clusterIndex}" ${cluster.prompts.length <= 4 || openGroups.has(clusterIndex) ? 'open' : ''}>
        <summary>Choose counts for ${cluster.prompts.length} subtask variant${cluster.prompts.length === 1 ? '' : 's'}</summary>
        <div class="episode-variant-list" data-variant-list></div>
      </details>
    </article>`;
  }).join('');
  setEpisodeGroupStatus(
    `${data.available_episode_count} usable episodes · ${data.prompt_count} source-prompt variants · ${data.clusters.length} local groups.`,
  );

  view.querySelectorAll('[data-episode-variants]').forEach((details) => {
    const renderRows = () => {
      const clusterIndex = Number(details.dataset.clusterIndex);
      if (details.open) openGroups.add(clusterIndex);
      else openGroups.delete(clusterIndex);
      if (details.open) {
        renderEpisodeVariantRows(
          dataset,
          clusterIndex,
          details.querySelector('[data-variant-list]'),
        );
      }
    };
    details.ontoggle = renderRows;
    renderRows();
  });
  view.querySelectorAll('[data-apply-group-target]').forEach((button) => {
    button.onclick = () => {
      const input = button.closest('.episode-group-bulk').querySelector('[data-group-variant-target]');
      if (input.value === '') {
        input.focus();
        setEpisodeGroupStatus('Enter a count before applying it to every variant.', 'bad');
        return;
      }
      applyGroupVariantTarget(
        dataset,
        Number(button.dataset.clusterIndex),
        Number(input.value),
      );
    };
  });
  view.querySelectorAll('[data-apply-group-cap]').forEach((button) => {
    button.onclick = () => {
      const input = button.closest('.episode-group-bulk').querySelector('[data-group-total-cap]');
      applyClusterCap(
        dataset,
        Number(button.dataset.clusterIndex),
        Number(input.value),
      );
    };
  });
}

function stageAllUsableEpisodes() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  if (!dataset || !dataset.valid) return;
  dataset.episodes.filter((episode) => !episode.exclusion_reason).forEach((episode) => stageEpisode(dataset, episode));
  finishEpisodeStage(dataset, `Staged all ${dataset.usable_episodes} usable episodes.`);
}

function clearEpisodeStage() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  if (!dataset) return;
  stagedEpisodesForDataset(dataset).forEach((episode) => unstageEpisode(dataset, episode.index));
  finishEpisodeStage(dataset, 'Cleared the temporary episode stage. The real recipe was not changed.');
}

function focusEpisode(dataset, episodeIndex) {
  const position = dataset.episodes.findIndex((episode) => episode.index === episodeIndex);
  if (position < 0) return;
  state.focusedEpisode = episodeIndex;
  state.episodeGalleryPages[dataset.path] = Math.floor(position / EPISODE_GALLERY_PAGE_SIZE);
  renderEpisodeBrowser();
}

function renderEpisodeBrowser() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  $('#stage-all-episodes').disabled = !dataset || !dataset.valid;
  $('#clear-stage').disabled = !dataset || stagedEpisodesForDataset(dataset).length === 0;
  $('#current-dataset').textContent = dataset ? `Reviewing ${dataset.name}: stage candidates first, then commit them in Tasks.` : 'Open a dataset from Sources to review every episode.';
  if (!dataset) {
    $('#episode-gallery').innerHTML = '';
    $('#episode-gallery-controls').innerHTML = '';
    $('#episode-detail').innerHTML = '<p class="empty">Choose a dataset first.</p>';
    renderEpisodeGroups(null);
    return;
  }
  renderEpisodeGroups(dataset);
  if (state.focusedEpisode === null || !dataset.episodes.some((episode) => episode.index === state.focusedEpisode)) state.focusedEpisode = dataset.episodes[0]?.index ?? null;
  const totalPages = Math.max(1, Math.ceil(dataset.episodes.length / EPISODE_GALLERY_PAGE_SIZE));
  const page = Math.max(0, Math.min(totalPages - 1, Number(state.episodeGalleryPages[dataset.path]) || 0));
  state.episodeGalleryPages[dataset.path] = page;
  const pageStart = page * EPISODE_GALLERY_PAGE_SIZE;
  const pageEpisodes = dataset.episodes.slice(pageStart, pageStart + EPISODE_GALLERY_PAGE_SIZE);
  const usablePageEpisodes = pageEpisodes.filter((episode) => !episode.exclusion_reason && dataset.valid);
  const stagedOnPage = usablePageEpisodes.filter((episode) => state.stagedEpisodes.has(episodeKey(dataset, episode.index))).length;
  const rangeStart = dataset.episodes.length ? pageStart + 1 : 0;
  $('#episode-gallery-controls').innerHTML = `<button type="button" class="quiet" data-gallery-previous ${page === 0 ? 'disabled' : ''}>←</button><span>Page ${page + 1} of ${totalPages}<small>${rangeStart}–${Math.min(pageStart + pageEpisodes.length, dataset.episodes.length)} of ${dataset.episodes.length}</small></span><button type="button" class="quiet" data-stage-page ${usablePageEpisodes.length === 0 || stagedOnPage === usablePageEpisodes.length ? 'disabled' : ''}>Stage page</button><button type="button" class="quiet" data-unstage-page ${stagedOnPage === 0 ? 'disabled' : ''}>Unstage page</button><button type="button" class="quiet" data-gallery-next ${page >= totalPages - 1 ? 'disabled' : ''}>→</button>`;
  $('#episode-gallery-controls [data-gallery-previous]').onclick = () => {
    state.episodeGalleryPages[dataset.path] = page - 1;
    renderEpisodeBrowser();
    $('#episode-gallery').scrollTop = 0;
  };
  $('#episode-gallery-controls [data-gallery-next]').onclick = () => {
    state.episodeGalleryPages[dataset.path] = page + 1;
    renderEpisodeBrowser();
    $('#episode-gallery').scrollTop = 0;
  };
  $('#episode-gallery-controls [data-stage-page]').onclick = () => {
    usablePageEpisodes.forEach((episode) => stageEpisode(dataset, episode));
    finishEpisodeStage(
      dataset,
      `Staged all ${usablePageEpisodes.length} usable episodes on page ${page + 1}.`,
    );
  };
  $('#episode-gallery-controls [data-unstage-page]').onclick = () => {
    usablePageEpisodes.forEach((episode) => unstageEpisode(dataset, episode.index));
    finishEpisodeStage(dataset, `Removed page ${page + 1} from the temporary stage.`);
  };
  $('#episode-gallery').innerHTML = pageEpisodes.map((episode) => {
    const task = dataset.tasks.find((item) => item.index === episode.task_index);
    const key = `${dataset.path}:${episode.index}`;
    const selected = state.choices.has(key);
    const staged = state.stagedEpisodes.has(key);
    const unavailable = Boolean(episode.exclusion_reason || !dataset.valid);
    const thumbnail = new URLSearchParams({ dataset_path: dataset.path, episode_index: episode.index });
    return `<article class="episode-tile ${selected ? 'selected' : ''} ${staged ? 'staged' : ''} ${state.focusedEpisode === episode.index ? 'focused' : ''} ${unavailable ? 'unavailable' : ''}">
      <button type="button" class="episode-tile-focus" data-focus-episode="${episode.index}" aria-label="Open episode ${episode.index}">
        <img loading="lazy" src="/api/thumbnail?${thumbnail}" alt="" onerror="this.hidden=true;this.nextElementSibling.hidden=false">
        <span class="thumbnail-fallback" hidden>No external thumbnail</span>
        <span class="episode-tile-title">Episode ${episode.index} · ${episode.duration_seconds.toFixed(1)}s ${selected ? '· Included' : ''}</span>
        <small>${escapeHtml(episode.exclusion_reason || task?.prompt || 'Untitled')}</small>
      </button>
      <label class="episode-tile-check"><input type="checkbox" data-gallery-stage="${episode.index}" ${staged ? 'checked' : ''} ${unavailable ? 'disabled' : ''}><span>${unavailable ? 'Unavailable' : 'Stage episode'}</span></label>
    </article>`;
  }).join('');
  $('#episode-gallery').querySelectorAll('[data-focus-episode]').forEach((button) => {
    button.onclick = () => {
      focusEpisode(dataset, Number(button.dataset.focusEpisode));
    };
  });
  $('#episode-gallery').querySelectorAll('[data-gallery-stage]').forEach((checkbox) => {
    checkbox.onchange = () => {
      const episode = dataset.episodes.find((item) => item.index === Number(checkbox.dataset.galleryStage));
      if (!episode) return;
      if (checkbox.checked) stageEpisode(dataset, episode);
      else unstageEpisode(dataset, episode.index);
      finishEpisodeStage(
        dataset,
        `Episode ${episode.index} ${checkbox.checked ? 'added to' : 'removed from'} the temporary stage.`,
      );
    };
  });
  renderFocusedEpisode(dataset);
}

function renderFocusedEpisode(dataset) {
  const position = dataset.episodes.findIndex((episode) => episode.index === state.focusedEpisode);
  const episode = dataset.episodes[position];
  if (!episode) {
    $('#episode-detail').innerHTML = '<p class="empty">No episodes available.</p>';
    return;
  }
  const key = `${dataset.path}:${episode.index}`;
  const selected = state.choices.has(key);
  const staged = state.stagedEpisodes.has(key);
  const task = dataset.tasks.find((item) => item.index === episode.task_index);
  const prompt = stagedPrompt(dataset, episode);
  const cameras = dataset.cameras.map((camera) => {
    const file = episode.video_files?.[camera];
    if (!file) return `<figure><figcaption>${escapeHtml(camera)}</figcaption><p class="empty">No indexed video for this episode.</p></figure>`;
    const query = new URLSearchParams({ dataset_path: dataset.path, episode_index: episode.index, camera });
    const start = episode.video_starts?.[camera] || 0;
    return `<figure><figcaption>${escapeHtml(camera)}</figcaption><div class="camera-video-slot" data-video-url="/api/preview?${query}#t=${start}"><p class="empty">Ready to load</p></div></figure>`;
  }).join('');
  $('#episode-detail').innerHTML = `<div class="episode-detail-head">
    <button class="quiet" data-prev ${position <= 0 ? 'disabled' : ''}>← Previous</button>
    <div><h3>Episode ${episode.index}</h3><p>${episode.duration_seconds.toFixed(1)}s · ${escapeHtml(task?.prompt || 'Untitled')}</p></div>
    <button class="quiet" data-next ${position >= dataset.episodes.length - 1 ? 'disabled' : ''}>Next →</button>
  </div>
  <button data-load-all>Load all available views</button>
  <div class="episode-previews">${cameras}</div>
  <p class="stage-detail-state"><strong>${selected ? 'Included in recipe' : 'Not included'}</strong><span>${staged ? 'Currently staged' : 'Not staged'}</span></p>
  <label>Staged final task prompt<input data-focused-prompt value="${escapeHtml(prompt)}"></label>
  <button data-toggle-stage ${episode.exclusion_reason || !dataset.valid ? 'disabled' : ''}>${staged ? 'Remove from stage' : 'Stage episode'}</button>`;
  $('#episode-detail [data-prev]').onclick = () => {
    focusEpisode(dataset, dataset.episodes[position - 1].index);
  };
  $('#episode-detail [data-next]').onclick = () => {
    focusEpisode(dataset, dataset.episodes[position + 1].index);
  };
  $('#episode-detail [data-load-all]').onclick = (event) => {
    $('#episode-detail').querySelectorAll('[data-video-url]').forEach((slot) => {
      slot.innerHTML = `<video controls preload="metadata" src="${slot.dataset.videoUrl}"></video>`;
    });
    event.currentTarget.disabled = true;
  };
  $('#episode-detail [data-toggle-stage]').onclick = () => {
    if (state.stagedEpisodes.has(key)) unstageEpisode(dataset, episode.index);
    else stageEpisode(dataset, episode);
    finishEpisodeStage(
      dataset,
      `Episode ${episode.index} ${state.stagedEpisodes.has(key) ? 'added to' : 'removed from'} the temporary stage.`,
    );
  };
  $('#episode-detail [data-focused-prompt]').oninput = (event) => {
    stageEpisode(dataset, episode);
    state.stagedPromptOverrides.set(key, event.target.value);
    $('#episode-detail [data-toggle-stage]').textContent = 'Remove from stage';
    $('#episode-detail .stage-detail-state span').textContent = 'Currently staged';
    renderSummary();
  };
}

function renderCatalog() {
  const term = $('#search').value.toLowerCase();
  const visible = state.catalog.filter((dataset) => JSON.stringify(dataset).toLowerCase().includes(term));
  const groups = new Map();
  visible.forEach((dataset) => {
    const source = dataset.name.split('/')[0];
    groups.set(source, [...(groups.get(source) || []), dataset]);
  });
  $('#catalog-count').textContent = `${groups.size} source folders · ${visible.length} recorded datasets`;
  const container = $('#catalog');
  container.innerHTML = '';
  [...groups.entries()].sort(([left], [right]) => left.localeCompare(right)).forEach(([source, datasets]) => {
    const group = document.createElement('details');
    group.className = 'source-group';
    group.open = datasets.length === 1;
    group.innerHTML = `<summary><span>${escapeHtml(source)}</span><small>${datasets.length} ${datasets.length === 1 ? 'dataset' : 'datasets'}</small></summary><div class="source-datasets"></div>`;
    const groupContent = group.querySelector('.source-datasets');
    datasets.forEach((dataset) => {
      const node = $('#card-template').content.firstElementChild.cloneNode(true);
      node.onmouseenter = () => { state.activeDataset = dataset.path; };
      node.onfocusin = () => { state.activeDataset = dataset.path; };
      node.querySelector('h3').textContent = dataset.name.replace(`${source}/`, '');
      node.querySelector('.meta').textContent = `${dataset.version || 'unknown'} · ${dataset.fps} FPS · ${dataset.cameras.length} cameras · ${dataset.usable_episodes}/${dataset.episodes.length} usable`;
      const status = node.querySelector('.status');
      status.textContent = dataset.valid ? (dataset.derived ? 'derived' : 'ready') : 'quarantined';
      status.classList.add(dataset.valid ? 'ready' : 'blocked');
      node.querySelector('.issues').textContent = dataset.issues.join(' · ');
      const checkpoint = state.sharedCheckpoints[dataset.path] || state.checkpoints[dataset.path];
      const owner = state.claims[dataset.path];
      node.querySelector('.issues').insertAdjacentHTML('afterend', `<p class="flag-actions">
        <button class="quiet" data-open ${owner && owner !== state.user ? 'disabled' : ''}>${owner === state.user ? 'Open my dataset' : 'Claim & open'}</button>
        <button class="quiet" data-draft ${owner !== state.user ? 'disabled' : ''}>Save draft</button>
        <button class="quiet" data-approve ${owner !== state.user ? 'disabled' : ''}>Approve checkpoint</button>
        <button class="quiet danger" data-exclude ${owner && owner !== state.user ? 'disabled' : ''}>Exclude…</button>
        <button class="quiet" data-history>History</button>
        <button class="quiet" data-release ${owner !== state.user ? 'disabled' : ''}>Release claim</button>
        ${owner ? `<small>claimed by ${escapeHtml(owner)}</small>` : ''}
        ${checkpoint ? `<small>${escapeHtml(checkpoint.status)} r${checkpoint.revision ?? 0}${checkpoint.status === 'excluded' && checkpoint.recipe?.reason ? ` · ${escapeHtml(checkpoint.recipe.reason)}` : ''}</small>` : ''}
      </p>`);
      node.querySelector('[data-open]').onclick = () => {
        if (owner === state.user) {
          state.currentDataset = dataset.path;
          state.focusedEpisode = null;
          hydrateDataset(dataset);
          renderEpisodeBrowser();
          renderChoices();
          renderCameraWorkspace();
          showPhase('cameras');
        } else claimCurrentDataset(dataset);
      };
      node.querySelector('[data-draft]').onclick = () => saveCheckpoint(dataset, 'draft');
      node.querySelector('[data-approve]').onclick = () => saveCheckpoint(dataset, 'approved');
      node.querySelector('[data-exclude]').onclick = () => excludeDataset(dataset);
      node.querySelector('[data-history]').onclick = (event) => toggleCheckpointHistory(dataset, event.currentTarget);
      node.querySelector('[data-release]').onclick = () => releaseClaim(dataset);
      node.querySelector('details').remove();
      const currentFlags = state.datasetFlags[dataset.path] || [];
      if (state.flags.length) {
        node.querySelector('.issues').insertAdjacentHTML('afterend', `<p class="flag-actions">${state.flags.map((flag, index) => `<button class="quiet" data-flag="${index}">${currentFlags.includes(index) ? '✓ ' : ''}${escapeHtml(flag.name)}</button>`).join('')}</p>`);
        node.querySelectorAll('[data-flag]').forEach((button) => {
          button.onclick = () => toggleDatasetFlag(dataset.path, Number(button.dataset.flag));
        });
      }
      groupContent.append(node);
    });
    container.append(group);
  });
}

async function loadCatalog() {
  $('#catalog').innerHTML = '<p class="empty">Scanning metadata and validating Parquet files…</p>';
  if (state.catalog.length) {
    state.episodeGroups = {};
    state.episodeGroupErrors = {};
  }
  const data = await apiJSON(`/api/catalog${state.catalog.length ? '?refresh=true' : ''}`);
  state.catalog = data.datasets;
  await Promise.all([loadWorkspaceRegistry(), loadWorkspace(), loadClaims(), loadSharedCheckpoints(), loadSettings()]);
  renderMetrics(data.summary);
  renderCatalog();
  renderSummary();
  renderCameraContract();
  updateBadges();
}

async function validateCurrentSelection() {
  const choices = [...state.choices.values()].map(({ dataset_path, episode_index, final_prompt }) => ({ dataset_path, episode_index, final_prompt }));
  $('#validation').innerHTML = '<p class="notice">Checking the current dataset recipe…</p>';
  try {
    const result = await apiJSON('/api/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ choices, camera_mappings: state.mappings, required_cameras: requiredCameras(), max_per_task: null }),
    });
    $('#validation').innerHTML = result.ok
      ? `<p class="notice good">Current recipe is valid: ${result.choices.length} episodes across ${Object.keys(result.task_counts).length} edited tasks.</p>`
      : `<ul class="notice bad">${result.errors.map((error) => `<li>${escapeHtml(error)}</li>`).join('')}</ul>`;
  } catch (error) {
    $('#validation').innerHTML = `<p class="notice bad">Validation failed: ${escapeHtml(error.message)}</p>`;
  }
}

function totalCount(counts) {
  return Object.values(counts || {}).reduce((sum, value) => sum + Number(value), 0);
}

async function refreshPreflight() {
  $('#balance-status').innerHTML = '<p class="notice">Reading approved checkpoints and building a deterministic manifest…</p>';
  $('#preflight-view').innerHTML = '<p class="notice">Running source, camera, schema, duration, prompt, duplicate, and destination checks…</p>';
  try {
    state.preflight = await apiJSON('/api/export/preflight', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ second_camera: state.settings.second_camera }),
    });
    state.preflightStale = false;
    state.preflightReason = '';
    renderGlobalBalance();
    renderPreflight();
    renderExportControls();
    updateBadges();
    await loadTaskGroups();
  } catch (error) {
    state.preflight = null;
    state.preflightStale = true;
    state.preflightReason = error.message;
    $('#balance-status').innerHTML = `<p class="notice bad">Could not load global balance: ${escapeHtml(error.message)}</p>`;
    $('#preflight-view').innerHTML = `<p class="notice bad">Preflight request failed: ${escapeHtml(error.message)}</p>`;
    renderExportControls();
    updateBadges();
  }
}

function renderGlobalBalance() {
  const selected = state.preflight?.selected_task_counts || {};
  const retained = state.preflight?.retained_task_counts || {};
  const tasks = [...new Set([...Object.keys(selected), ...Object.keys(retained)])].sort((left, right) => left.localeCompare(right));
  const selectedTotal = totalCount(selected);
  const retainedTotal = totalCount(retained);
  $('#balance-status').innerHTML = state.preflight
    ? `<p class="notice ${state.preflight.ok ? 'good' : ''}">Counts include approved shared checkpoints only. ${state.settings.max_per_task ? `The global cap is ${state.settings.max_per_task} episodes per edited task.` : 'No per-task cap is configured.'} ${(state.taskGroups?.clusters || []).filter((cluster) => cluster.episode_cap !== null).length} task-group cap${(state.taskGroups?.clusters || []).filter((cluster) => cluster.episode_cap !== null).length === 1 ? '' : 's'} active.</p>`
    : '<p class="empty">Run preflight to load approved checkpoint counts.</p>';
  $('#balance-stats').innerHTML = `<span><strong>${selectedTotal}</strong> approved selections</span><span><strong>${retainedTotal}</strong> retained</span><span><strong>${tasks.length}</strong> edited tasks</span>`;
  $('#balance-view').hidden = state.balanceViewMode !== 'prompts';
  $('#task-group-view').hidden = state.balanceViewMode !== 'groups';
  $('#balance-view-mode').value = state.balanceViewMode;
  $('#balance-view').innerHTML = tasks.length
    ? `<div class="balance-row balance-head"><span>Edited task</span><b>Selected</b><b>Retained</b><span>Retention</span></div>${tasks.map((task) => {
      const selectedCount = Number(selected[task] || 0);
      const retainedCount = Number(retained[task] || 0);
      const percent = selectedCount ? Math.round((retainedCount / selectedCount) * 100) : 0;
      return `<div class="balance-row"><span title="${escapeHtml(task)}">${escapeHtml(task)}</span><b>${selectedCount}</b><b>${retainedCount}</b><div class="retention-bar" title="${percent}% retained"><i style="width:${percent}%"></i></div></div>`;
    }).join('')}`
    : '<p class="empty">No approved episodes are available. Approve a curated dataset checkpoint, then refresh.</p>';
  renderTaskGroups();
}

function taskGroupDisplayName(cluster) {
  return cluster.approved_name || cluster.suggested_name || 'Awaiting a group name';
}

function renderTaskGroups() {
  const view = $('#task-group-view');
  const button = $('#generate-task-groups');
  const groups = state.taskGroups?.clusters || [];
  const selected = state.preflight?.selected_task_counts || {};
  const retained = state.preflight?.retained_task_counts || {};
  const groqPromptLimit = Number(state.taskGroups?.groq_prompt_limit || 400);
  const exceedsGroqPromptLimit = Number(state.taskGroups?.prompt_count || 0) > groqPromptLimit;
  view.hidden = state.balanceViewMode !== 'groups';
  $('#balance-view').hidden = state.balanceViewMode !== 'prompts';
  $('#balance-view-mode').value = state.balanceViewMode;

  button.disabled = state.taskGroupsLoading
    || !state.taskGroups?.groq_configured
    || exceedsGroqPromptLimit
    || groups.length === 0;
  button.textContent = state.taskGroupsLoading ? 'Naming task groups…' : 'Generate names with Groq';

  if (!state.taskGroups) {
    view.innerHTML = '<p class="empty">Task groups have not been loaded.</p>';
    return;
  }
  if (!groups.length) {
    view.innerHTML = '<p class="empty">Approve checkpoints containing selected episodes to create task groups.</p>';
    return;
  }

  view.innerHTML = groups.map((cluster) => {
    const prompts = cluster.prompts || [];
    const selectedCount = prompts.reduce((sum, prompt) => sum + Number(selected[prompt.text] || 0), 0);
    const retainedCount = prompts.reduce((sum, prompt) => sum + Number(retained[prompt.text] || 0), 0);
    const availableCount = Math.max(selectedCount, Number(cluster.selected || 0));
    const savedCap = cluster.episode_cap === null ? null : Number(cluster.episode_cap);
    const sliderValue = savedCap === null ? availableCount : Math.min(savedCap, availableCount);
    const capLabel = savedCap === null ? `All ${availableCount}` : `${sliderValue} of ${availableCount}`;
    const capSaving = state.taskGroupCapSaving.has(cluster.id);
    const status = cluster.approved_name ? 'Approved' : cluster.suggested_name ? 'Groq suggestion' : 'Unlabeled';
    return `<article class="task-group-card" data-task-group="${escapeHtml(cluster.id)}">
      <header>
        <div><span class="group-state ${cluster.approved_name ? 'approved' : ''}">${status}</span><h4>${escapeHtml(taskGroupDisplayName(cluster))}</h4><p>${escapeHtml(cluster.signature?.action || 'task')} · ${escapeHtml(String(cluster.signature?.relation || 'general').replaceAll('_', ' '))}</p></div>
        <dl><div><dt>Selected</dt><dd>${selectedCount}</dd></div><div><dt>Retained</dt><dd>${retainedCount}</dd></div><div><dt>Prompts</dt><dd>${prompts.length}</dd></div></dl>
      </header>
      <div class="task-group-name-editor">
        <label>Group name<input data-group-name value="${escapeHtml(cluster.approved_name || cluster.suggested_name || '')}" maxlength="80" placeholder="Review or enter a concise group name"></label>
        <button type="button" class="quiet" data-approve-group>Approve name</button>
      </div>
      <div class="task-group-cap">
        <div class="task-group-cap-heading"><label for="cap-${escapeHtml(cluster.id)}">Final dataset group cap</label><output data-group-cap-output>${capLabel}</output></div>
        <div class="task-group-cap-controls">
          <input id="cap-${escapeHtml(cluster.id)}" data-group-cap type="range" min="0" max="${availableCount}" step="1" value="${sliderValue}" ${capSaving || availableCount === 0 ? 'disabled' : ''}>
          <input data-group-cap-number type="number" min="0" max="${availableCount}" step="1" value="${sliderValue}" aria-label="Exact episode cap for ${escapeHtml(taskGroupDisplayName(cluster))}" ${capSaving || availableCount === 0 ? 'disabled' : ''}>
          <button type="button" class="quiet" data-clear-group-cap ${capSaving || savedCap === null ? 'disabled' : ''}>Use all</button>
        </div>
        <small>${capSaving ? 'Saving cap and refreshing preflight…' : 'Applied after the per-prompt cap. Set 0 to omit this group; maximum means no group cap.'}</small>
      </div>
      <details>
        <summary>View ${prompts.length} unchanged prompt${prompts.length === 1 ? '' : 's'}</summary>
        <div class="task-group-prompts">${prompts.map((prompt) => {
          const promptSelected = Number(selected[prompt.text] || 0);
          const promptRetained = Number(retained[prompt.text] || 0);
          return `<div><span title="${escapeHtml(prompt.text)}">${escapeHtml(prompt.text)}</span><b>${promptSelected}</b><b>${promptRetained}</b></div>`;
        }).join('')}</div>
      </details>
    </article>`;
  }).join('');

  view.querySelectorAll('[data-approve-group]').forEach((approveButton) => {
    approveButton.onclick = () => {
      const card = approveButton.closest('[data-task-group]');
      approveTaskGroupName(card.dataset.taskGroup, card.querySelector('[data-group-name]').value);
    };
  });
  view.querySelectorAll('[data-task-group]').forEach((card) => {
    const range = card.querySelector('[data-group-cap]');
    const number = card.querySelector('[data-group-cap-number]');
    const output = card.querySelector('[data-group-cap-output]');
    const clear = card.querySelector('[data-clear-group-cap]');
    const available = Number(range.max);
    const updatePreview = (value) => {
      const normalized = Math.max(0, Math.min(available, Math.round(Number(value) || 0)));
      range.value = normalized;
      number.value = normalized;
      output.textContent = normalized === available ? `All ${available}` : `${normalized} of ${available}`;
      return normalized;
    };
    range.oninput = () => updatePreview(range.value);
    number.oninput = () => updatePreview(number.value);
    range.onchange = () => saveTaskGroupCap(card.dataset.taskGroup, updatePreview(range.value), available);
    number.onchange = () => saveTaskGroupCap(card.dataset.taskGroup, updatePreview(number.value), available);
    clear.onclick = () => saveTaskGroupCap(card.dataset.taskGroup, available, available);
  });
}

function setTaskGroupStatus(message, kind = '') {
  const status = $('#task-group-status');
  status.innerHTML = message ? `<p class="notice ${kind}">${escapeHtml(message)}</p>` : '';
}

async function loadTaskGroups() {
  try {
    state.taskGroups = await apiJSON('/api/task-groups');
    const model = state.taskGroups.groq_model || 'configured model';
    const promptLimit = Number(state.taskGroups.groq_prompt_limit || 400);
    const exceedsPromptLimit = Number(state.taskGroups.prompt_count || 0) > promptLimit;
    setTaskGroupStatus(
      exceedsPromptLimit
        ? `${state.taskGroups.prompt_count} unique approved prompts exceed the local ${promptLimit}-prompt Groq naming safeguard. No Groq request was sent; local groups and balancing still work.`
        : state.taskGroups.groq_configured
        ? `Local embeddings are ready. Groq model: ${model}. Names are suggestions until approved.`
        : 'Local embeddings are ready. Set GROQ_API_KEY on the server to generate group names.',
      exceedsPromptLimit ? 'bad' : state.taskGroups.groq_configured ? 'good' : '',
    );
  } catch (error) {
    state.taskGroups = null;
    setTaskGroupStatus(`Could not load task groups: ${error.message}`, 'bad');
  }
  renderGlobalBalance();
}

async function suggestTaskGroupNames() {
  const promptLimit = Number(state.taskGroups?.groq_prompt_limit || 400);
  if (
    state.taskGroupsLoading
    || !state.taskGroups?.groq_configured
    || Number(state.taskGroups?.prompt_count || 0) > promptLimit
  ) return;
  state.taskGroupsLoading = true;
  setTaskGroupStatus('Sending unchanged prompt text—not checkpoint files or dataset paths—to Groq for group naming.');
  renderTaskGroups();
  try {
    state.taskGroups = await apiJSON('/api/task-groups/suggest', { method: 'POST' });
    setTaskGroupStatus('Groq suggestions received. Review and approve each name; prompts remain unchanged.', 'good');
  } catch (error) {
    setTaskGroupStatus(`Groq naming failed without saving partial results: ${error.message}`, 'bad');
  } finally {
    state.taskGroupsLoading = false;
    renderTaskGroups();
  }
}

async function approveTaskGroupName(clusterId, name) {
  const normalized = name.trim();
  if (!normalized) {
    setTaskGroupStatus('Enter a group name before approving it.', 'bad');
    return;
  }
  try {
    state.taskGroups = await apiJSON(`/api/task-groups/${encodeURIComponent(clusterId)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: normalized }),
    });
    setTaskGroupStatus(`Approved “${normalized}” for balancing. No task prompts were changed.`, 'good');
  } catch (error) {
    setTaskGroupStatus(`Could not approve group name: ${error.message}`, 'bad');
  }
  renderTaskGroups();
}

async function saveTaskGroupCap(clusterId, requestedCap, available) {
  if (state.taskGroupCapSaving.has(clusterId)) return;
  const episodeCap = requestedCap >= available ? null : requestedCap;
  state.taskGroupCapSaving.add(clusterId);
  setTaskGroupStatus(
    episodeCap === null
      ? 'Removing the group cap and refreshing the frozen selection preview…'
      : `Saving a ${episodeCap}-episode group cap and refreshing the frozen selection preview…`,
  );
  renderTaskGroups();
  try {
    state.taskGroups = await apiJSON(`/api/task-groups/${encodeURIComponent(clusterId)}/cap`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ episode_cap: episodeCap }),
    });
    markPreflightStale('A task-group episode cap changed.');
    await refreshPreflight();
    setTaskGroupStatus(
      episodeCap === null
        ? 'Group cap cleared. All available episodes may be retained.'
        : `Group cap saved at ${episodeCap} episode${episodeCap === 1 ? '' : 's'} and applied to preflight.`,
      'good',
    );
    setSaveStatus(
      episodeCap === null
        ? 'Task-group cap cleared · changes saved'
        : `Task-group cap ${episodeCap} · changes saved`,
      'saved',
    );
  } catch (error) {
    setTaskGroupStatus(`Could not save group cap: ${error.message}`, 'bad');
  } finally {
    state.taskGroupCapSaving.delete(clusterId);
    renderGlobalBalance();
  }
}

function errorGuidance(error) {
  const guidance = {
    cameras: 'Map exactly one source view to wrist and one to the configured second camera.',
    joints: 'Map action and observation.state into the six canonical robot joint slots.',
    episodes: 'Open the dataset and correct its episode selection or edited prompt.',
    sources: 'Inspect the source dataset and its quarantine reason.',
    output: 'Choose a new valid destination or output name.',
    balance: 'Set a positive global task cap in Output.',
    preflight: 'The source schema or media must be repaired before export.',
  };
  return guidance[error.phase] || 'Resolve this blocker and rerun preflight.';
}

function focusError(error) {
  const dataset = state.catalog.find((item) => item.path === error.dataset_path);
  if (dataset && state.currentDataset !== dataset.path && ['cameras', 'joints', 'episodes'].includes(error.phase)) {
    $('#search').value = dataset.name;
    renderCatalog();
    showPhase('sources');
    setSaveStatus(`Open ${dataset.name} to resolve its ${error.category} blocker.`, 'failed');
    return;
  }
  const knownPhases = new Set(['sources', 'output', 'cameras', 'joints', 'episodes', 'tasks', 'balance', 'preflight', 'export']);
  showPhase(knownPhases.has(error.phase) ? error.phase : 'sources');
}

function renderPreflight() {
  if (state.preflightStale) {
    $('#preflight-summary').innerHTML = '';
    $('#preflight-view').innerHTML = `<p class="notice bad"><strong>Preflight is stale.</strong> ${escapeHtml(state.preflightReason)}</p>`;
    $('#manifest-preview').innerHTML = '<p class="empty">Run preflight to freeze a new manifest preview.</p>';
    $('#manifest-count').textContent = '';
    return;
  }
  const plan = state.preflight;
  if (!plan) return;
  const errors = plan.errors || [];
  $('#preflight-summary').innerHTML = `<span><strong>${plan.episodes?.length || 0}</strong> retained episodes</span><span><strong>${plan.tasks?.length || 0}</strong> tasks</span><span><strong>${errors.length}</strong> blockers</span><span><strong>2</strong> output cameras</span>`;
  if (!errors.length) {
    $('#preflight-view').innerHTML = `<p class="notice good"><strong>Ready to export.</strong> Every retained approved episode has compatible data, exactly one wrist mapping, one ${escapeHtml(state.settings.second_camera)} mapping, and readable media.</p>`;
  } else {
    const groups = new Map();
    errors.forEach((error, index) => {
      const key = error.dataset_path || '__project__';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push({ ...error, index });
    });
    $('#preflight-view').innerHTML = `<div class="blocker-groups">${[...groups.entries()].map(([path, group]) => {
      const dataset = state.catalog.find((item) => item.path === path);
      const title = dataset?.name || (path === '__project__' ? 'Project settings' : path);
      const revision = group[0].checkpoint_revision;
      return `<article class="blocker-group">
        <div class="blocker-head"><div><small>${path === '__project__' ? 'PROJECT' : `CHECKPOINT · REVISION ${revision ?? '?'}`}</small><h3>${escapeHtml(title)}</h3></div><span>${group.length} ${group.length === 1 ? 'blocker' : 'blockers'}</span></div>
        <ul>${group.map((error) => `<li><div><b>${escapeHtml(error.category)}</b><p>${escapeHtml(error.message)}</p><small>${escapeHtml(errorGuidance(error))}</small></div><button class="quiet" data-error-index="${error.index}">Go to ${escapeHtml(error.phase || 'Sources')}</button></li>`).join('')}</ul>
      </article>`;
    }).join('')}</div>`;
    $('#preflight-view').querySelectorAll('[data-error-index]').forEach((button) => {
      button.onclick = () => focusError(errors[Number(button.dataset.errorIndex)]);
    });
  }
  renderManifestPreview(plan);
}

function renderManifestPreview(plan) {
  const episodes = plan.episodes || [];
  $('#manifest-count').textContent = `${episodes.length} episodes · showing ${Math.min(episodes.length, 20)}`;
  $('#manifest-preview').innerHTML = episodes.length
    ? `<div class="table-scroll"><table class="manifest-table"><thead><tr><th>Output</th><th>Source dataset</th><th>Episode</th><th>Edited task</th><th>Cameras</th><th>Revision</th></tr></thead><tbody>${episodes.slice(0, 20).map((episode) => `<tr>
      <td>#${episode.output_episode_index}</td>
      <td title="${escapeHtml(episode.dataset_path)}">${escapeHtml(episode.dataset_name || episode.dataset_path)}</td>
      <td>${episode.source_episode_index}</td>
      <td>${escapeHtml(episode.final_prompt)}</td>
      <td>${(episode.cameras || []).map((camera) => escapeHtml(camera.canonical_name)).join(' + ')}</td>
      <td>r${episode.checkpoint_revision} · ${escapeHtml(episode.updated_by)}</td>
    </tr>`).join('')}</tbody></table></div>`
    : '<p class="empty">No retained episodes to preview.</p>';
}

function jobId(job) {
  return String(job.job_id || job.id || '');
}

function isActiveJob(job) {
  return ['queued', 'running', 'cancelling'].includes(job.status);
}

function jobProgress(job) {
  const completed = Number(job.completed_episodes ?? job.episodes_completed ?? job.completed ?? 0);
  const total = Number(job.total_episodes ?? job.episode_count ?? job.total ?? state.preflight?.episodes?.length ?? 0);
  const suppliedProgress = Number(job.progress);
  if (Number.isFinite(suppliedProgress)) {
    const raw = suppliedProgress;
    return { completed, total, percent: Math.max(0, Math.min(100, raw <= 1 ? raw * 100 : raw)) };
  }
  return { completed, total, percent: total ? Math.round((completed / total) * 100) : 0 };
}

function renderExportControls() {
  const select = $('#export-second-camera');
  const selected = select.value || state.settings.second_camera;
  fillCameraSelect(select, selected);
  const matches = select.value === state.settings.second_camera;
  const ready = Boolean(state.preflight && state.preflight.ok && !state.preflightStale && matches);
  const active = state.jobs.some(isActiveJob);
  $('#export-readiness').textContent = ready ? 'Preflight ready' : state.preflightStale ? 'Preflight stale' : 'Blocked';
  $('#export-readiness').className = `readiness ${ready ? 'ready' : 'blocked'}`;
  if (!matches) {
    $('#export-warning').innerHTML = `<p class="notice bad">Final camera differs from Output settings. Applying it will invalidate the current manifest and every incompatible approved mapping.</p>`;
  } else if (state.preflightStale) {
    $('#export-warning').innerHTML = `<p class="notice bad">${escapeHtml(state.preflightReason)}</p>`;
  } else if (state.preflight && !state.preflight.ok) {
    $('#export-warning').innerHTML = `<p class="notice bad">Resolve ${state.preflight.errors.length} preflight blocker${state.preflight.errors.length === 1 ? '' : 's'} before export.</p>`;
  } else {
    $('#export-warning').innerHTML = `<p class="notice good">Manifest ready: ${state.preflight?.episodes?.length || 0} episodes will be normalized to wrist + ${escapeHtml(state.settings.second_camera)}.</p>`;
  }
  $('#recheck-export').textContent = matches ? 'Rerun preflight' : 'Apply camera & rerun preflight';
  $('#export-button').disabled = !ready || !$('#export-confirm').checked || active;
}

function normalizeJobs(payload) {
  if (Array.isArray(payload)) return payload;
  return payload.jobs || [];
}

async function loadJobs() {
  try {
    state.jobs = normalizeJobs(await apiJSON('/api/export/jobs'));
    const active = state.jobs.find((job) => jobId(job) === state.activeJobId) || state.jobs.find(isActiveJob);
    if (active) {
      state.activeJobId = jobId(active);
      const detail = await apiJSON(`/api/export/jobs/${encodeURIComponent(state.activeJobId)}`);
      const resolved = detail.job || detail;
      state.jobs = state.jobs.map((job) => jobId(job) === state.activeJobId ? resolved : job);
    } else {
      state.activeJobId = null;
    }
    renderJobs();
    scheduleJobPolling();
  } catch (error) {
    $('#jobs-view').innerHTML = `<p class="notice bad">Could not load export jobs: ${escapeHtml(error.message)}</p>`;
  }
}

function renderJobs() {
  const rank = { running: 0, queued: 1, cancelling: 2, failed: 3, cancelled: 4, completed: 5 };
  const jobs = [...state.jobs].sort((left, right) => (rank[left.status] ?? 9) - (rank[right.status] ?? 9));
  $('#jobs-view').innerHTML = jobs.length ? jobs.map((job) => {
    const id = jobId(job);
    const progress = jobProgress(job);
    const cameraProgress = Number(job.total_cameras) > 0
      ? `${Number(job.completed_cameras || 0)}/${Number(job.total_cameras)} cameras`
      : '';
    const currentParts = [
      job.current_stage,
      job.current_dataset,
      job.current_episode !== undefined && job.current_episode !== null ? `episode ${job.current_episode}` : '',
      job.current_camera,
      cameraProgress,
    ].filter(Boolean);
    const outputPath = job.final_path || job.output_path;
    const archiveStatus = job.archive_status || 'not_requested';
    let archiveControl = '';
    if (job.status === 'completed') {
      if (archiveStatus === 'ready') {
        archiveControl = `<a class="button-link" data-download-archive href="/api/export/jobs/${encodeURIComponent(id)}/download" download>Download .tar.gz</a>`;
      } else if (archiveStatus === 'preparing') {
        archiveControl = '<button class="quiet" disabled>Preparing .tar.gz…</button><small class="archive-status">Packaging is running in the background.</small>';
      } else {
        archiveControl = `<button class="quiet" data-prepare-archive="${escapeHtml(id)}">${archiveStatus === 'failed' ? 'Retry .tar.gz' : 'Prepare .tar.gz'}</button>${job.archive_error ? `<small class="archive-status failed">${escapeHtml(job.archive_error)}</small>` : ''}`;
      }
    }
    return `<article class="job-card ${escapeHtml(job.status || 'unknown')}">
      <div class="job-head"><div><small>JOB ${escapeHtml(id)}</small><h3>${escapeHtml(job.status || 'unknown')}</h3></div><strong>${Math.round(progress.percent)}%</strong></div>
      <div class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(progress.percent)}"><i style="width:${progress.percent}%"></i></div>
      <p>${progress.total ? `${progress.completed} of ${progress.total} episodes` : 'Waiting for episode count'}${currentParts.length ? ` · ${escapeHtml(currentParts.join(' · '))}` : ''}</p>
      ${job.error ? `<pre class="job-error">${escapeHtml(job.error)}</pre>` : ''}
      ${outputPath ? `<p class="output-path"><span>Output</span><code>${escapeHtml(outputPath)}</code></p>` : ''}
      ${job.manifest_path ? `<p class="output-path"><span>Manifest</span><code>${escapeHtml(job.manifest_path)}</code></p>` : ''}
      ${isActiveJob(job) ? `<button class="quiet danger" data-cancel-job="${escapeHtml(id)}" ${job.status === 'cancelling' ? 'disabled' : ''}>${job.status === 'cancelling' ? 'Cancelling…' : 'Cancel export'}</button>` : ''}
      ${archiveControl ? `<div class="archive-actions">${archiveControl}</div>` : ''}
    </article>`;
  }).join('') : '<p class="empty">No exports have been started. Completed and failed jobs remain visible here after restart.</p>';
  $('#jobs-view').querySelectorAll('[data-cancel-job]').forEach((button) => {
    button.onclick = () => cancelJob(button.dataset.cancelJob);
  });
  $('#jobs-view').querySelectorAll('[data-prepare-archive]').forEach((button) => {
    button.onclick = () => prepareArchive(button.dataset.prepareArchive);
  });
  updateBadges();
  renderExportControls();
}

function scheduleJobPolling() {
  clearTimeout(state.jobPollTimer);
  if (state.jobs.some((job) => isActiveJob(job) || job.archive_status === 'preparing')) {
    state.jobPollTimer = setTimeout(loadJobs, 2000);
  }
}

async function startExport() {
  renderExportControls();
  if ($('#export-button').disabled) return;
  $('#export-button').disabled = true;
  $('#export-warning').innerHTML = '<p class="notice">Queuing export and persisting its frozen manifest…</p>';
  try {
    const result = await apiJSON('/api/export/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ second_camera: state.settings.second_camera }),
    });
    const job = result.job || result;
    state.activeJobId = jobId(job);
    state.jobs = [job, ...state.jobs.filter((item) => jobId(item) !== state.activeJobId)];
    $('#export-confirm').checked = false;
    renderJobs();
    scheduleJobPolling();
  } catch (error) {
    $('#export-warning').innerHTML = `<p class="notice bad">Could not start export: ${escapeHtml(error.message)}</p>`;
    renderExportControls();
  }
}

async function cancelJob(id) {
  try {
    const result = await apiJSON(`/api/export/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' });
    const job = result.job || result;
    state.jobs = state.jobs.map((item) => jobId(item) === id ? job : item);
    renderJobs();
    scheduleJobPolling();
  } catch (error) {
    $('#jobs-view').insertAdjacentHTML('afterbegin', `<p class="notice bad">Cancellation failed: ${escapeHtml(error.message)}</p>`);
  }
}

async function prepareArchive(id) {
  const button = document.querySelector(`[data-prepare-archive="${CSS.escape(id)}"]`);
  if (button) {
    button.disabled = true;
    button.textContent = 'Preparing .tar.gz…';
  }
  try {
    const job = await apiJSON(`/api/export/jobs/${encodeURIComponent(id)}/archive`, { method: 'POST' });
    state.jobs = state.jobs.map((item) => jobId(item) === id ? job : item);
    renderJobs();
    scheduleJobPolling();
  } catch (error) {
    $('#jobs-view').insertAdjacentHTML('afterbegin', `<p class="notice bad">Archive preparation failed: ${escapeHtml(error.message)}</p>`);
    if (button) button.disabled = false;
  }
}

$('#search').addEventListener('input', renderCatalog);
$('#refresh').onclick = loadCatalog;
$('#validate').onclick = validateCurrentSelection;
$('#stage-all-episodes').onclick = stageAllUsableEpisodes;
$('#clear-stage').onclick = clearEpisodeStage;
$('#release-all').onclick = releaseAllMyClaims;
$('#workspace-select').onchange = (event) => {
  state.selectedWorkspaceId = event.target.value;
  renderWorkspaceControls();
};
$('#new-workspace').onclick = openNewWorkspaceDialog;
$('#switch-workspace').onclick = openSwitchWorkspaceDialog;
$('#new-workspace-form').onsubmit = (event) => {
  event.preventDefault();
  startNewWorkspace();
};
$('#switch-workspace-form').onsubmit = (event) => {
  event.preventDefault();
  switchWorkspace();
};
$('#new-workspace-form').oninput = updateNewWorkspaceConfirmation;
$('#switch-workspace-confirmation').oninput = updateSwitchWorkspaceConfirmation;
document.querySelectorAll('[data-dialog-cancel]').forEach((button) => {
  button.onclick = () => button.closest('dialog').close();
});
document.querySelectorAll('.workspace-dialog').forEach((dialog) => {
  dialog.addEventListener('cancel', (event) => {
    if (state.workspaceTransitionPending) event.preventDefault();
  });
});
$('#user-name').value = state.user;
$('#user-name').onchange = async (event) => {
  state.user = event.target.value.trim() || 'operator';
  state.currentDataset = null;
  localStorage.setItem('dataset-studio-user', state.user);
  await Promise.all([loadWorkspace(), loadClaims(), loadSharedCheckpoints()]);
  renderCatalog();
  showPhase('sources');
};
document.querySelectorAll('.phase-tab').forEach((tab) => {
  tab.onclick = () => showPhase(tab.dataset.phase);
});
$('#add-flag').onclick = () => {
  const name = $('#flag-name').value.trim();
  if (!name) return;
  state.flags.push({ name, rule: $('#flag-rule').value.trim() });
  $('#flag-name').value = '';
  $('#flag-rule').value = '';
  state.catalog.forEach((dataset) => {
    if (state.flags.at(-1).rule && JSON.stringify(dataset).toLowerCase().includes(state.flags.at(-1).rule.toLowerCase())) toggleDatasetFlag(dataset.path, state.flags.length - 1);
  });
  renderFlags();
  renderCatalog();
  scheduleAutosave();
};
$('#output-settings-form').onsubmit = async (event) => {
  event.preventDefault();
  await saveProjectSettings();
};
$('#output-settings-form').oninput = () => {
  setSettingsStatus('Unsaved project settings.', 'saving');
  markPreflightStale('Output settings have unsaved changes.');
};
$('#bulk-task-prompt').oninput = () => updateStagingControls();
$('#apply-bulk-task-prompt').onclick = applyBulkTaskPrompt;
$('#include-staged-episodes').onclick = () => commitStagedEpisodes(true);
$('#unselect-staged-episodes').onclick = () => commitStagedEpisodes(false);
$('#clear-staged-episodes').onclick = clearStagedEpisodes;
$('#check-included-page').onclick = () => {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  if (!dataset) return;
  const included = includedEpisodesForDataset(dataset);
  const page = Number(state.includedEpisodePages[dataset.path]) || 0;
  included
    .slice(page * INCLUDED_EPISODE_PAGE_SIZE, (page + 1) * INCLUDED_EPISODE_PAGE_SIZE)
    .forEach(({ choice }) => state.includedEpisodeSelection.add(choice.key));
  renderIncludedEpisodes(dataset);
};
$('#clear-included-checks').onclick = () => {
  state.includedEpisodeSelection.clear();
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  renderIncludedEpisodes(dataset);
};
$('#exclude-checked-included').onclick = excludeCheckedIncludedEpisodes;
$('#clear-all-included').onclick = clearAllIncludedEpisodes;
$('#refresh-balance').onclick = refreshPreflight;
$('#generate-task-groups').onclick = suggestTaskGroupNames;
$('#balance-view-mode').onchange = (event) => {
  state.balanceViewMode = event.target.value === 'prompts' ? 'prompts' : 'groups';
  localStorage.setItem('dataset-studio-balance-view', state.balanceViewMode);
  renderGlobalBalance();
};
$('#run-preflight').onclick = refreshPreflight;
$('#export-second-camera').onchange = () => {
  $('#export-confirm').checked = false;
  renderExportControls();
};
$('#export-confirm').onchange = renderExportControls;
$('#recheck-export').onclick = async () => {
  const selected = $('#export-second-camera').value;
  if (selected !== state.settings.second_camera) {
    const saved = await saveProjectSettings({ useExportCamera: true });
    if (!saved) return;
  }
  await refreshPreflight();
};
$('#export-button').onclick = startExport;
$('#refresh-jobs').onclick = loadJobs;
document.addEventListener('keydown', (event) => {
  if (state.workspaceTransitionPending) return;
  if (!event.ctrlKey || event.key < '1' || event.key > '9' || !state.activeDataset) return;
  event.preventDefault();
  toggleDatasetFlag(state.activeDataset, Number(event.key) - 1);
});

loadCatalog().catch((error) => {
  $('#catalog').innerHTML = `<p class="notice bad">Could not load catalog: ${escapeHtml(error.message)}</p>`;
});
