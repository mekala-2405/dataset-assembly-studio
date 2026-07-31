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
  dirty: false,
  settings: { ...DEFAULT_SETTINGS },
  settingsLoaded: false,
  preflight: null,
  preflightStale: true,
  preflightReason: 'Run preflight after reviewing Output settings.',
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
  if (phase === 'tasks') $('#tasks-view').innerHTML = $('#summary').innerHTML;
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
  select.disabled = !active;
  $('#new-workspace').disabled = !active;
  $('#switch-workspace').disabled = !active || state.selectedWorkspaceId === active.id;
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
  $('#start-new-workspace').disabled = !(currentName.trim()
    && newName.trim()
    && confirmation === 'START NEW WORKSPACE');
}

function updateSwitchWorkspaceConfirmation() {
  const activeWorkspaceId = state.workspaceRegistry?.active_workspace_id;
  const confirmation = $('#switch-workspace-confirmation').value;
  $('#confirm-switch-workspace').disabled = !(state.selectedWorkspaceId !== activeWorkspaceId
    && confirmation === 'SWITCH WORKSPACE');
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

async function startNewWorkspace() {
  const currentName = $('#new-workspace-current-name').value.trim();
  const newName = $('#new-workspace-name').value.trim();
  const confirmation = $('#new-workspace-confirmation').value;
  if (!currentName || !newName || confirmation !== 'START NEW WORKSPACE') return;
  const dialog = $('#new-workspace-dialog');
  clearTimeout(state.saveTimer);
  const current = state.catalog.find((item) => item.path === state.currentDataset);
  if (current && state.dirty) {
    const saved = await persistCheckpoint(current, 'draft');
    if (!saved) {
      setWorkspaceDialogError(dialog, 'Could not save the current workspace. Resolve the save error before continuing.');
      return;
    }
  }
  try {
    await apiJSON('/api/workspaces/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_name: currentName, new_name: newName, confirmation }),
    });
    dialog.close();
    completeWorkspaceTransition();
  } catch (error) {
    setWorkspaceDialogError(dialog, `Could not start workspace: ${error.message}`);
    updateNewWorkspaceConfirmation();
  }
}

async function switchWorkspace() {
  const activeWorkspaceId = state.workspaceRegistry?.active_workspace_id;
  const confirmation = $('#switch-workspace-confirmation').value;
  if (state.selectedWorkspaceId === activeWorkspaceId || confirmation !== 'SWITCH WORKSPACE') return;
  const dialog = $('#switch-workspace-dialog');
  clearTimeout(state.saveTimer);
  const current = state.catalog.find((item) => item.path === state.currentDataset);
  if (current && state.dirty) {
    const saved = await persistCheckpoint(current, 'draft');
    if (!saved) {
      setWorkspaceDialogError(dialog, 'Could not save the current workspace. Resolve the save error before continuing.');
      return;
    }
  }
  try {
    await apiJSON('/api/workspaces/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_id: state.selectedWorkspaceId, confirmation }),
    });
    dialog.close();
    completeWorkspaceTransition();
  } catch (error) {
    setWorkspaceDialogError(dialog, `Could not switch workspace: ${error.message}`);
    updateSwitchWorkspaceConfirmation();
  }
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

async function persistCheckpoint(dataset, status = 'draft', refreshCatalog = false) {
  setSaveStatus('Saving…', 'saving');
  try {
    const result = await apiJSON('/api/checkpoints', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: state.user, dataset_path: dataset.path, status, recipe: recipeForDataset(dataset) }),
    });
    state.checkpoints = result.checkpoints || state.checkpoints;
    if (result.shared_checkpoint) state.sharedCheckpoints[dataset.path] = result.shared_checkpoint;
    state.dirty = false;
    setSaveStatus(`Changes saved · revision ${result.shared_checkpoint?.revision ?? '?'}`, 'saved');
    markPreflightStale(`${dataset.name} checkpoint changed; refresh approved data.`);
    if (refreshCatalog) renderCatalog();
    return true;
  } catch (error) {
    setSaveStatus(`Save failed: ${error.message}`, 'failed');
    return false;
  }
}

function scheduleAutosave(datasetPath = state.currentDataset) {
  if (!datasetPath || state.claims[datasetPath] !== state.user) return;
  clearTimeout(state.saveTimer);
  state.dirty = true;
  setSaveStatus('Unsaved changes', 'saving');
  state.saveTimer = setTimeout(() => {
    const dataset = state.catalog.find((item) => item.path === datasetPath);
    if (dataset) persistCheckpoint(dataset, 'draft');
  }, 500);
}

async function claimCurrentDataset(dataset) {
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
  } catch (error) {
    alert(error.message);
  }
}

async function saveCheckpoint(dataset, status) {
  await persistCheckpoint(dataset, status, true);
}

async function excludeDataset(dataset) {
  const reason = window.prompt('Reason for excluding this dataset from export:', dataset.valid ? '' : (dataset.issues.join('; ') || 'quarantined source'));
  if (reason === null || !reason.trim()) return;
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
  } catch (error) {
    setSaveStatus(`Exclude failed: ${error.message}`, 'failed');
  }
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
  if (state.dirty) await persistCheckpoint(dataset, 'draft');
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
  } catch (error) {
    setSaveStatus(`Release failed: ${error.message}`, 'failed');
  }
}

async function releaseAllMyClaims() {
  clearTimeout(state.saveTimer);
  const current = state.catalog.find((item) => item.path === state.currentDataset);
  if (current && state.claims[current.path] === state.user && state.dirty) await persistCheckpoint(current, 'draft');
  try {
    const result = await apiJSON(`/api/claims/user/${encodeURIComponent(state.user)}`, { method: 'DELETE' });
    state.claims = result.claims || {};
    state.currentDataset = null;
    setSaveStatus('All claims released · saved changes retained', 'saved');
    renderCatalog();
    showPhase('sources');
  } catch (error) {
    setSaveStatus(`Release failed: ${error.message}`, 'failed');
  }
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
  $('#episode-selection-stats').innerHTML = `<span><strong>${state.choices.size}</strong> selected episodes</span><span><strong>${Object.keys(counts).length}</strong> edited tasks</span>`;
  if (state.currentPhase === 'tasks') $('#tasks-view').innerHTML = $('#summary').innerHTML;
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

function selectAllUsableEpisodes() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  if (!dataset || !dataset.valid) return;
  dataset.episodes.filter((episode) => !episode.exclusion_reason).forEach((episode) => addChoice(dataset, episode, false));
  renderEpisodeBrowser();
  renderSummary();
  updateBadges();
  scheduleAutosave(dataset.path);
}

function clearEpisodeSelection() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  if (!dataset) return;
  [...state.choices.entries()].forEach(([key, choice]) => {
    if (choice.dataset_path === dataset.path) state.choices.delete(key);
  });
  renderEpisodeBrowser();
  renderSummary();
  updateBadges();
  scheduleAutosave(dataset.path);
}

function renderEpisodeBrowser() {
  const dataset = state.catalog.find((item) => item.path === state.currentDataset);
  $('#select-all-episodes').disabled = !dataset || !dataset.valid;
  $('#clear-episodes').disabled = !dataset || ![...state.choices.values()].some((choice) => choice.dataset_path === dataset.path);
  $('#current-dataset').textContent = dataset ? `Reviewing ${dataset.name}: choose and edit any individual episode.` : 'Open a dataset from Sources to review every episode.';
  if (!dataset) {
    $('#episode-gallery').innerHTML = '';
    $('#episode-detail').innerHTML = '<p class="empty">Choose a dataset first.</p>';
    return;
  }
  if (state.focusedEpisode === null || !dataset.episodes.some((episode) => episode.index === state.focusedEpisode)) state.focusedEpisode = dataset.episodes[0]?.index ?? null;
  $('#episode-gallery').innerHTML = dataset.episodes.map((episode) => {
    const task = dataset.tasks.find((item) => item.index === episode.task_index);
    const key = `${dataset.path}:${episode.index}`;
    const selected = state.choices.has(key);
    const thumbnail = new URLSearchParams({ dataset_path: dataset.path, episode_index: episode.index });
    return `<button class="episode-tile ${selected ? 'selected' : ''} ${state.focusedEpisode === episode.index ? 'focused' : ''}" data-focus-episode="${episode.index}">
      <img loading="lazy" src="/api/thumbnail?${thumbnail}" alt="" onerror="this.hidden=true;this.nextElementSibling.hidden=false">
      <span class="thumbnail-fallback" hidden>No external thumbnail</span>
      <span class="episode-tile-title">Episode ${episode.index} · ${episode.duration_seconds.toFixed(1)}s</span>
      <small>${escapeHtml(episode.exclusion_reason || task?.prompt || 'Untitled')}</small>
      ${selected ? '<b>Selected</b>' : ''}
    </button>`;
  }).join('');
  $('#episode-gallery').querySelectorAll('[data-focus-episode]').forEach((button) => {
    button.onclick = () => {
      state.focusedEpisode = Number(button.dataset.focusEpisode);
      renderEpisodeBrowser();
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
  const selected = state.choices.get(key);
  const task = dataset.tasks.find((item) => item.index === episode.task_index);
  const prompt = selected?.final_prompt ?? task?.prompt ?? '';
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
  <label>Final task prompt<input data-focused-prompt value="${escapeHtml(prompt)}"></label>
  <button data-toggle-selection ${episode.exclusion_reason || !dataset.valid ? 'disabled' : ''}>${selected ? 'Deselect episode' : 'Select episode'}</button>`;
  $('#episode-detail [data-prev]').onclick = () => {
    state.focusedEpisode = dataset.episodes[position - 1].index;
    renderEpisodeBrowser();
  };
  $('#episode-detail [data-next]').onclick = () => {
    state.focusedEpisode = dataset.episodes[position + 1].index;
    renderEpisodeBrowser();
  };
  $('#episode-detail [data-load-all]').onclick = (event) => {
    $('#episode-detail').querySelectorAll('[data-video-url]').forEach((slot) => {
      slot.innerHTML = `<video controls preload="metadata" src="${slot.dataset.videoUrl}"></video>`;
    });
    event.currentTarget.disabled = true;
  };
  $('#episode-detail [data-toggle-selection]').onclick = () => {
    if (state.choices.has(key)) state.choices.delete(key);
    else addChoice(dataset, episode);
    renderEpisodeBrowser();
    renderSummary();
    updateBadges();
    scheduleAutosave(dataset.path);
  };
  $('#episode-detail [data-focused-prompt]').oninput = (event) => {
    if (!state.choices.has(key)) addChoice(dataset, episode);
    state.choices.get(key).final_prompt = event.target.value;
    renderSummary();
    updateBadges();
    scheduleAutosave(dataset.path);
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
    ? `<p class="notice ${state.preflight.ok ? 'good' : ''}">Counts include approved shared checkpoints only. ${state.settings.max_per_task ? `The global cap is ${state.settings.max_per_task} episodes per edited task.` : 'No per-task cap is configured.'}</p>`
    : '<p class="empty">Run preflight to load approved checkpoint counts.</p>';
  $('#balance-stats').innerHTML = `<span><strong>${selectedTotal}</strong> approved selections</span><span><strong>${retainedTotal}</strong> retained</span><span><strong>${tasks.length}</strong> edited tasks</span>`;
  $('#balance-view').innerHTML = tasks.length
    ? `<div class="balance-row balance-head"><span>Edited task</span><b>Selected</b><b>Retained</b><span>Retention</span></div>${tasks.map((task) => {
      const selectedCount = Number(selected[task] || 0);
      const retainedCount = Number(retained[task] || 0);
      const percent = selectedCount ? Math.round((retainedCount / selectedCount) * 100) : 0;
      return `<div class="balance-row"><span title="${escapeHtml(task)}">${escapeHtml(task)}</span><b>${selectedCount}</b><b>${retainedCount}</b><div class="retention-bar" title="${percent}% retained"><i style="width:${percent}%"></i></div></div>`;
    }).join('')}`
    : '<p class="empty">No approved episodes are available. Approve a curated dataset checkpoint, then refresh.</p>';
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
$('#select-all-episodes').onclick = selectAllUsableEpisodes;
$('#clear-episodes').onclick = clearEpisodeSelection;
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
$('#refresh-balance').onclick = refreshPreflight;
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
  if (!event.ctrlKey || event.key < '1' || event.key > '9' || !state.activeDataset) return;
  event.preventDefault();
  toggleDatasetFlag(state.activeDataset, Number(event.key) - 1);
});

loadCatalog().catch((error) => {
  $('#catalog').innerHTML = `<p class="notice bad">Could not load catalog: ${escapeHtml(error.message)}</p>`;
});
