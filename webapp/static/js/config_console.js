const ANALOG_PRESETS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const SELECT_PRESETS = [17, 18, 19, 20, 21, 35, 36, 37, 39, 40, 41, 42, 45];
const API_BASE = '';
const PCB_MODELS = {
  'v2.2.c': '/static/images/v2.2.c.png',
  'v2.1': '/static/images/v2.1.png',
};
const DEFAULT_MODEL = 'v2.2.c';

const deviceSelect = document.getElementById('device-select');
const refreshDevicesBtn = document.getElementById('refresh-devices');
const refreshResultsBtn = document.getElementById('refresh-results');
const deviceMeta = document.getElementById('device-meta');
const modelSelect = document.getElementById('model-select');
const analogInput = document.getElementById('analog-input');
const selectInput = document.getElementById('select-input');
const deviceCountEl = document.getElementById('device-count');
const agentCountEl = document.getElementById('agent-count');
const formFeedback = document.getElementById('form-feedback');
const form = document.getElementById('config-form');
const clearBtn = document.getElementById('clear-form');
const pcbPreview = document.getElementById('pcb-preview');
const analogSelection = document.getElementById('analog-selection');
const selectSelection = document.getElementById('select-selection');
const devicesTableBody = document.getElementById('devices-table-body');
const historyTableBody = document.getElementById('history-table-body');
const licenseDefaults = window.licenseDefaults || {};
const licenseForm = document.getElementById('license-form');
const licenseDnInput = document.getElementById('license-dn');
const licenseIpInput = document.getElementById('license-ip');
const licenseMacInput = document.getElementById('license-mac');
const licenseTierSelect = document.getElementById('license-tier');
const licenseDaysInput = document.getElementById('license-days');
const licensePortInput = document.getElementById('license-port');
const licenseFeedback = document.getElementById('license-feedback');
const licenseOutput = document.getElementById('license-output');
const licenseQueryBtn = document.getElementById('license-query');
const licenseKeyState = document.getElementById('license-key-state');
const manualDnInput = document.getElementById('manual-dn');
const manualIpInput = document.getElementById('manual-ip');
const dnDatalist = document.getElementById('device-dn-options');
const controlForm = document.getElementById('control-form');
const controlAction = document.getElementById('control-action');
const controlFeedback = document.getElementById('control-feedback');
const controlPortInput = document.getElementById('control-port');
const controlLevelInput = document.getElementById('control-level');
const controlAlphaInput = document.getElementById('control-alpha');
const controlMedianInput = document.getElementById('control-median');
const controlAnalogInput = document.getElementById('control-analogpin');
const controlSelectInput = document.getElementById('control-selectpin');
const controlStartTimeInput = document.getElementById('control-start-time');
const controlCalibTimeInput = document.getElementById('control-calib-time');
const controlPathInput = document.getElementById('control-path');
const controlLimitInput = document.getElementById('control-limit');
const controlWriteText = document.getElementById('control-write-text');
const controlFileInput = document.getElementById('control-file');
const controlEnabledCheckbox = document.getElementById('control-enabled');

const state = {
  devices: [],
  results: [],
  discovery: {
    broadcast: [],
  },
};

const fetchJSON = async (path, options = {}) => {
  const resp = await fetch(`${API_BASE}${path}`, options);
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || detail.error || resp.statusText);
  }
  return resp.json();
};

const parsePins = (value) =>
  Array.from(
    new Set(
      (value || '')
        .split(/[^0-9]+/)
        .map((v) => v.trim())
        .filter(Boolean)
        .map((v) => Number(v))
        .filter((n) => Number.isFinite(n))
    )
  );

const formatDateTime = (value) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  const pad = (num) => String(num).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
};

const setFormFeedback = (message = '', isError = false) => {
  if (!formFeedback) return;
  formFeedback.textContent = message;
  formFeedback.dataset.state = isError ? 'error' : 'info';
};

const setLicenseFeedback = (message = '', isError = false) => {
  if (!licenseFeedback) return;
  licenseFeedback.textContent = message;
  licenseFeedback.dataset.state = isError ? 'error' : 'info';
};

const setControlFeedback = (message = '', isError = false) => {
  if (!controlFeedback) return;
  controlFeedback.textContent = message;
  controlFeedback.dataset.state = isError ? 'error' : 'info';
};

const normalizeMac = (value = '') => (value || '').replace(/[^0-9a-fA-F]/g, '').toUpperCase();
const normalizeDn = (value = '') => (value || '').replace(/[^0-9a-fA-F]/g, '').toUpperCase();

const applyLicenseDefaults = () => {
  if (licenseDaysInput && licenseDefaults.days) {
    licenseDaysInput.value = licenseDefaults.days;
  }
  if (licenseTierSelect && licenseDefaults.tier) {
    licenseTierSelect.value = licenseDefaults.tier;
  }
  if (licensePortInput) {
    const port = Number(licenseDefaults.port || licensePortInput.placeholder || 0);
    if (port) {
      licensePortInput.value = port;
    }
  }
  if (licenseKeyState) {
    const enabled = licenseDefaults.enabled !== false;
    licenseKeyState.textContent = enabled ? 'License service ready' : 'License service unavailable';
    licenseKeyState.dataset.state = enabled ? 'ok' : 'off';
  }
};

function syncLicenseInputsFromDevice() {
  if (!deviceSelect) return;
  const option = deviceSelect.selectedOptions[0];
  if (!option) return;
  const dn = option.value || '';
  const ip = option.dataset.ip || '';
  if (licenseDnInput) {
    licenseDnInput.value = dn;
  }
  if (licenseMacInput && (!licenseMacInput.value || licenseMacInput.dataset.autoFilled === '1')) {
    licenseMacInput.value = dn;
    licenseMacInput.dataset.autoFilled = '1';
  }
  if (licenseIpInput && (!licenseIpInput.value || licenseIpInput.dataset.autoFilled === '1')) {
    licenseIpInput.value = ip;
    licenseIpInput.dataset.autoFilled = '1';
  }
}

function syncManualInputsFromDevice() {
  const option = deviceSelect?.selectedOptions?.[0];
  if (!option) return;
  const dn = option.value || '';
  const ip = option.dataset.ip || '';
  if (manualDnInput && (!manualDnInput.value || manualDnInput.dataset.autoFilled === '1')) {
    manualDnInput.value = dn;
    manualDnInput.dataset.autoFilled = '1';
  }
  if (manualIpInput && (!manualIpInput.value || manualIpInput.dataset.autoFilled === '1')) {
    manualIpInput.value = ip;
    manualIpInput.dataset.autoFilled = '1';
  }
}

const formatLicenseOutput = (payload = {}) => {
  const lines = [];
  if (payload.command_id) lines.push(`command_id: ${payload.command_id}`);
  if (payload.status) lines.push(`status: ${payload.status}`);
  if (payload.token) lines.push(`token: ${payload.token}`);
  if (payload.tier) lines.push(`tier: ${payload.tier}`);
  if (payload.device_code) lines.push(`device_code: ${payload.device_code}`);
  if (payload.dn) lines.push(`dn: ${payload.dn}`);
  if (payload.target_ip) lines.push(`target_ip: ${payload.target_ip}`);
  if (payload.port) lines.push(`port: ${payload.port}`);
  if (payload.expiry_iso || payload.expiry) {
    lines.push(`expiry: ${payload.expiry_iso || payload.expiry}`);
  }
  if (payload.reply) lines.push(`device_reply: ${payload.reply}`);
  if (payload.licenses) lines.push(`licenses: ${JSON.stringify(payload.licenses)}`);
  if (payload.raw && !payload.reply) lines.push(`raw: ${payload.raw}`);
  if (!lines.length) return JSON.stringify(payload, null, 2);
  return lines.join('\n');
};

const updateModelPreview = () => {
  if (!modelSelect || !pcbPreview) return;
  const model = modelSelect.value || DEFAULT_MODEL;
  const src = PCB_MODELS[model] || PCB_MODELS[DEFAULT_MODEL];
  pcbPreview.src = src;
  pcbPreview.alt = `PCB layout preview (${model})`;
};

const selectionLabels = {
  'analog-input': analogSelection,
  'select-input': selectSelection,
};

const updatePinSelectionLabel = (targetInputId, pins) => {
  const label = selectionLabels[targetInputId];
  if (!label) return;
  const prefix = label.dataset.label || 'Selected pins';
  label.textContent = pins.length ? `${prefix}: ${pins.join(', ')}` : `${prefix}: none`;
};

function renderPinButtons(containerId, pins, targetInput) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '';
  pins.forEach((pin) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'pin-btn';
    btn.textContent = pin;
    btn.dataset.pin = pin;
    btn.dataset.target = targetInput;
    btn.addEventListener('click', onPinButtonClick);
    container.appendChild(btn);
  });
}

function syncPinButtons(targetInputId) {
  const input = document.getElementById(targetInputId);
  if (!input) return;
  const pins = parsePins(input.value);
  document
    .querySelectorAll(`.pin-btn[data-target="${targetInputId}"]`)
    .forEach((btn) => {
      const value = Number(btn.dataset.pin);
      btn.setAttribute('aria-pressed', pins.includes(value));
    });
  updatePinSelectionLabel(targetInputId, pins);
}

function onPinButtonClick(event) {
  const btn = event.currentTarget;
  const input = document.getElementById(btn.dataset.target);
  const value = Number(btn.dataset.pin);
  const pins = parsePins(input.value);
  const index = pins.indexOf(value);
  if (index >= 0) pins.splice(index, 1);
  else pins.push(value);
  input.value = pins.join(',');
  syncPinButtons(btn.dataset.target);
}

function renderDeviceOptions(selectedDn = '') {
  deviceSelect.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Select a device';
  deviceSelect.appendChild(placeholder);

  state.devices.forEach((device) => {
    const option = document.createElement('option');
    option.value = device.dn || '';
    option.textContent = device.ip ? `${device.dn} (${device.ip})` : device.dn || '';
    option.dataset.ip = device.ip || '';
    option.dataset.lastSeen = device.last_seen || '';
    option.dataset.agent = device.agent_id || '';
    option.dataset.model = device.model || '';
    deviceSelect.appendChild(option);
  });

  if (selectedDn) {
    const exists = Array.from(deviceSelect.options).some((option) => option.value === selectedDn);
    if (exists) {
      deviceSelect.value = selectedDn;
    }
  }

  renderDnOptions();
}

function renderDnOptions() {
  if (!dnDatalist) return;
  dnDatalist.innerHTML = '';
  const seen = new Set();
  state.devices.forEach((device) => {
    const dn = device.dn || '';
    if (!dn || seen.has(dn)) return;
    seen.add(dn);
    const opt = document.createElement('option');
    opt.value = dn;
    dnDatalist.appendChild(opt);
  });
}

function renderDeviceTable() {
  devicesTableBody.innerHTML = '';
  if (!state.devices.length) {
    devicesTableBody.innerHTML = '<tr><td colspan="3" class="table-empty">No data</td></tr>';
    return;
  }
  state.devices.forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${item.dn || ''}</code></td>
      <td>${item.ip || '-'}</td>
      <td>${formatDateTime(item.last_seen)}</td>
    `;
    tr.addEventListener('click', () => {
      if (!item.dn) return;
      deviceSelect.value = item.dn;
      deviceSelect.dispatchEvent(new Event('change'));
    });
    devicesTableBody.appendChild(tr);
  });
}

function renderHistoryTable() {
  historyTableBody.innerHTML = '';
  if (!state.results.length) {
    historyTableBody.innerHTML = '<tr><td colspan="4" class="table-empty">No data</td></tr>';
    return;
  }
  state.results.forEach((item) => {
    const replyStatus = (item.reply && item.reply.status) ? String(item.reply.status).toLowerCase() : '';
    const overallStatus = (item.status || replyStatus || '').toLowerCase();
    const isOk = overallStatus ? overallStatus === 'ok' : replyStatus === 'ok';
    const statusClass = isOk ? 'status-ok' : 'status-error';
    const detailPayload = item.error || item.reply || item.payload || {};
    const detail = typeof detailPayload === 'string' ? detailPayload : JSON.stringify(detailPayload || {});
    const statusLabel = overallStatus || replyStatus || (isOk ? 'ok' : 'error');
    const payloadType = item.payload && item.payload.type ? String(item.payload.type).toLowerCase() : '';
    const dnLabel = (payloadType === 'discover' || item.method === 'discover' || (item.dn || '').toUpperCase() === 'BROADCAST')
      ? 'broadcast'
      : (item.dn || '');
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="font-mono">${formatDateTime(item.timestamp)}</span></td>
      <td><code>${dnLabel}</code></td>
      <td class="${statusClass}">${statusLabel}</td>
      <td><code>${detail}</code></td>
    `;
    historyTableBody.appendChild(tr);
  });
}

function updateMetrics() {
  deviceCountEl.textContent = `Devices: ${state.devices.length}`;
  const agents = new Set(state.devices.map((item) => item.agent_id).filter(Boolean));
  agentCountEl.textContent = `Agents: ${agents.size || '--'}`;
}

function updateDeviceMeta(option) {
  if (!option || !option.value) {
    if (manualIpInput && manualIpInput.value) {
      deviceMeta.textContent = `Manual IP: ${manualIpInput.value}`;
      return;
    }
    deviceMeta.textContent = state.devices.length ? `${state.devices.length} devices online` : 'No device selected';
    return;
  }
  const ip = option.dataset.ip;
  const lastSeen = option.dataset.lastSeen;
  const heartbeat = lastSeen ? `Last heartbeat: ${formatDateTime(lastSeen)}` : 'Last heartbeat: unknown';
  deviceMeta.textContent = ip ? `${ip} | ${heartbeat}` : heartbeat;
}

async function loadDevices() {
  const selectedDn = deviceSelect.value || normalizeDn(manualDnInput?.value || '');
  deviceMeta.textContent = 'Sending broadcast discover...';
  try {
    await fetchJSON('/api/discover', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
  } catch (error) {
    deviceMeta.textContent = `Discover queued failed: ${error.message}`;
  }
  deviceMeta.textContent = 'Loading devices...';
  try {
    const data = await fetchJSON('/api/devices');
    state.devices = (data.items || []).map((item) => ({
      ...item,
      dn: normalizeDn(item.dn || item.mac || item.device_code || ''),
      ip: item.ip || '',
    }));
    state.discovery.broadcast = [];
    deviceMeta.textContent = state.devices.length ? `${state.devices.length} devices online` : 'No devices online';
  } catch (error) {
    deviceMeta.textContent = error.message;
    return;
  }
  renderDeviceOptions(selectedDn);
  if (!deviceSelect.value && state.devices.length === 1) {
    deviceSelect.value = state.devices[0].dn || '';
  }
  renderDeviceTable();
  updateMetrics();
  updateDeviceMeta(deviceSelect.selectedOptions[0]);
  syncLicenseInputsFromDevice();
  syncManualInputsFromDevice();
}

async function loadResults() {
  try {
    const data = await fetchJSON('/api/commands/latest');
    state.results = data.items || [];
    renderHistoryTable();
  } catch (error) {
    setFormFeedback(`Failed to load history: ${error.message}`, true);
  }
}

async function handleLicenseSubmit(event) {
  event.preventDefault();
  if (!licenseForm) return;
  if (licenseDefaults && licenseDefaults.enabled === false) {
    setLicenseFeedback('License 服务未启用。', true);
    return;
  }
  const dn = (licenseDnInput?.value || manualDnInput?.value || deviceSelect.value || '').trim().toUpperCase();
  const mac = normalizeMac((licenseMacInput?.value || dn || '').trim());
  const days = Number(licenseDaysInput?.value || licenseDefaults.days || 0);
  const tier = (licenseTierSelect?.value || licenseDefaults.tier || 'basic').trim().toLowerCase();
  let targetIp = (licenseIpInput?.value || manualIpInput?.value || '').trim();
  if (!targetIp && deviceSelect?.selectedOptions?.length) {
    targetIp = deviceSelect.selectedOptions[0].dataset.ip || '';
  }
  const portVal = Number(licensePortInput?.value || licenseDefaults.port || 0);

  if (!mac || mac.length !== 12) {
    setLicenseFeedback('请输入 12 位设备码（可带冒号）。', true);
    return;
  }
  if (!Number.isInteger(days) || days <= 0) {
    setLicenseFeedback('有效天数需为正整数。', true);
    return;
  }
  const payload = {
    device_code: mac,
    days,
    tier,
  };
  if (dn) payload.dn = dn;
  if (targetIp) payload.target_ip = targetIp;
  if (Number.isInteger(portVal) && portVal > 0) payload.port = portVal;

  setLicenseFeedback('正在生成并下发 license...', false);
  if (licenseOutput) {
    licenseOutput.textContent = 'processing...';
  }
  try {
    const resp = await fetchJSON('/api/license/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    setLicenseFeedback('命令已发布，等待采集端执行。', false);
    if (licenseOutput) {
      licenseOutput.textContent = formatLicenseOutput(resp);
    }
  } catch (error) {
    setLicenseFeedback(`下发失败: ${error.message}`, true);
    if (licenseOutput) {
      licenseOutput.textContent = error.message;
    }
  }
}

async function handleLicenseQuery() {
  if (licenseDefaults && licenseDefaults.enabled === false) {
    setLicenseFeedback('License 服务未启用。', true);
    return;
  }
  const dn = (licenseDnInput?.value || manualDnInput?.value || deviceSelect.value || '').trim().toUpperCase();
  let targetIp = (licenseIpInput?.value || manualIpInput?.value || '').trim();
  if (!targetIp && deviceSelect?.selectedOptions?.length) {
    targetIp = deviceSelect.selectedOptions[0].dataset.ip || '';
  }
  const portVal = Number(licensePortInput?.value || licenseDefaults.port || 0);
  if (!targetIp) {
    setLicenseFeedback('请先选择设备或填写目标 IP。', true);
    return;
  }
  const qs = new URLSearchParams();
  qs.set('target_ip', targetIp);
  if (dn) qs.set('dn', dn);
  if (Number.isInteger(portVal) && portVal > 0) qs.set('port', portVal);

  setLicenseFeedback('查询中...', false);
  if (licenseOutput) {
    licenseOutput.textContent = 'querying...';
  }
  try {
    const resp = await fetchJSON(`/api/license/query?${qs.toString()}`);
    setLicenseFeedback('查询命令已发布，等待采集端返回。', false);
    if (licenseOutput) {
      licenseOutput.textContent = formatLicenseOutput(resp);
    }
  } catch (error) {
    setLicenseFeedback(`查询失败: ${error.message}`, true);
    if (licenseOutput) {
      licenseOutput.textContent = error.message;
    }
  }
}

function onDeviceChange() {
  updateDeviceMeta(deviceSelect.selectedOptions[0]);
  syncLicenseInputsFromDevice();
  syncManualInputsFromDevice();
}

async function handleSubmit(event) {
  event.preventDefault();
  const dn = normalizeDn((manualDnInput?.value || deviceSelect.value || '').trim());
  const model = (modelSelect && modelSelect.value) || DEFAULT_MODEL;
  if (!dn) {
    setFormFeedback('Please select a device or input DN/MAC before sending.', true);
    return;
  }
  const analogPins = parsePins(analogInput.value);
  const selectPins = parsePins(selectInput.value);
  if (!analogPins.length || !selectPins.length) {
    setFormFeedback('Analog and select pins cannot be empty.', true);
    return;
  }
  const payload = {
    dn,
    analog: analogPins,
    select: selectPins,
    model,
  };

  const targetIp = (manualIpInput?.value || deviceSelect.selectedOptions?.[0]?.dataset.ip || '').trim();
  const body = { ...payload };
  if (targetIp) {
    body.target_ip = targetIp;
  }

  setFormFeedback('Sending command via MQTT...', false);
  try {
    const resp = await fetchJSON('/api/config/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (manualDnInput && resp.dn) {
      manualDnInput.value = resp.dn;
      manualDnInput.dataset.autoFilled = '1';
    }
    setFormFeedback(`Command ${resp.command_id || ''} queued via MQTT.`, false);
    loadResults();
  } catch (error) {
    setFormFeedback(`Failed to send: ${error.message}`, true);
  }
}

function clearForm() {
  deviceSelect.value = '';
  analogInput.value = '';
  selectInput.value = '';
  if (controlForm) {
    controlForm.reset();
  }
  if (manualDnInput) {
    manualDnInput.value = '';
    manualDnInput.dataset.autoFilled = '0';
  }
  if (manualIpInput) {
    manualIpInput.value = '';
    manualIpInput.dataset.autoFilled = '0';
  }
  if (modelSelect) {
    modelSelect.value = DEFAULT_MODEL;
    updateModelPreview();
  }
  syncPinButtons('analog-input');
  syncPinButtons('select-input');
  deviceSelect.dispatchEvent(new Event('change'));
  setFormFeedback('');
}

function debounce(fn, wait = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(null, args), wait);
  };
}

function init() {
  applyLicenseDefaults();
  renderPinButtons('analog-grid', ANALOG_PRESETS, 'analog-input');
  renderPinButtons('select-grid', SELECT_PRESETS, 'select-input');
  syncPinButtons('analog-input');
  syncPinButtons('select-input');
  deviceSelect.addEventListener('change', onDeviceChange);
  if (modelSelect) {
    modelSelect.addEventListener('change', updateModelPreview);
    updateModelPreview();
  }
  refreshDevicesBtn.addEventListener('click', () => loadDevices());
  refreshResultsBtn.addEventListener('click', () => loadResults());
  form.addEventListener('submit', handleSubmit);
  clearBtn.addEventListener('click', clearForm);
  if (licenseMacInput) {
    licenseMacInput.addEventListener('input', () => {
      licenseMacInput.dataset.autoFilled = '0';
    });
  }
  if (licenseIpInput) {
    licenseIpInput.addEventListener('input', () => {
      licenseIpInput.dataset.autoFilled = '0';
    });
  }
  if (manualDnInput) {
    manualDnInput.addEventListener('input', () => {
      manualDnInput.dataset.autoFilled = '0';
    });
  }
  if (manualIpInput) {
    manualIpInput.addEventListener('input', () => {
      manualIpInput.dataset.autoFilled = '0';
    });
  }
  if (licenseForm) {
    licenseForm.addEventListener('submit', handleLicenseSubmit);
  }
  if (licenseQueryBtn) {
    licenseQueryBtn.addEventListener('click', handleLicenseQuery);
  }
  if (controlForm) {
    controlForm.addEventListener('submit', handleControlSubmit);
  }
  if (licenseForm && licenseDefaults && licenseDefaults.enabled === false) {
    Array.from(licenseForm.elements).forEach((el) => {
      if (el.id !== 'license-output') el.disabled = true;
    });
    setLicenseFeedback('License 服务未启用。', true);
  }
  loadDevices();
  loadResults();
  setInterval(loadResults, 8000);
}

init();
function getNumeric(input) {
  if (!input) return undefined;
  const val = input.value;
  if (val === undefined || val === null || val === '') return undefined;
  const num = Number(val);
  return Number.isFinite(num) ? num : undefined;
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve((reader.result || '').toString().split(',').pop());
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function handleControlSubmit(event) {
  event.preventDefault();
  const dn = normalizeDn((manualDnInput?.value || deviceSelect.value || '').trim());
  if (!dn) {
    setControlFeedback('请先选择设备或输入 DN/MAC。', true);
    return;
  }
  const action = controlAction?.value || '';
  if (!action) {
    setControlFeedback('请选择命令。', true);
    return;
  }
  const targetIp = (manualIpInput?.value || deviceSelect.selectedOptions?.[0]?.dataset.ip || '').trim();
  const port = getNumeric(controlPortInput);
  let payload = {};

  const levelVal = controlLevelInput?.value || '';
  const alphaVal = getNumeric(controlAlphaInput);
  const medianVal = getNumeric(controlMedianInput);
  const analogpinVal = getNumeric(controlAnalogInput);
  const selectpinVal = getNumeric(controlSelectInput);
  const startTimeVal = getNumeric(controlStartTimeInput);
  const calibTimeVal = getNumeric(controlCalibTimeInput);
  const pathVal = (controlPathInput?.value || '').trim();
  const limitVal = getNumeric(controlLimitInput);
  const enabledChecked = controlEnabledCheckbox?.checked;
  const writeText = controlWriteText?.value || '';
  const fileObj = controlFileInput?.files?.[0];

  switch (action) {
    case 'standby_enable':
      payload = { standby: { command: 'enable' } };
      break;
    case 'standby_disable':
      payload = { standby: { command: 'disable' } };
      break;
    case 'filter_query':
      payload = { filter: '?' };
      break;
    case 'filter_set': {
      const filter = {};
      if (enabledChecked !== undefined) filter.enabled = !!enabledChecked;
      if (alphaVal !== undefined) filter.alpha = alphaVal;
      if (medianVal !== undefined) filter.median = medianVal;
      payload = { filter };
      break;
    }
    case 'calib_enable':
      payload = { calibration: { command: 'enabled' } };
      break;
    case 'calib_disable':
      payload = { calibration: { command: 'disabled' } };
      break;
    case 'calib_status':
      payload = { calibration: { command: '?' } };
      break;
    case 'calib_collect':
      if (analogpinVal === undefined || selectpinVal === undefined || !levelVal) {
        setControlFeedback('AnalogPin / SelectPin / level 不能为空。', true);
        return;
      }
      payload = {
        calibration: {
          command: 'calibration',
          analogpin: analogpinVal,
          selectpin: selectpinVal,
          level: Number(levelVal),
          start_time: startTimeVal ?? 1000,
          calibration_time: calibTimeVal ?? 5000,
        },
      };
      break;
    case 'calib_level_query':
      if (!levelVal) {
        setControlFeedback('请输入 level。', true);
        return;
      }
      payload = { calibration: { command: 'level', level: levelVal } };
      break;
    case 'calib_level_delete':
      if (!levelVal) {
        setControlFeedback('请输入 level。', true);
        return;
      }
      payload = { calibration: { command: 'delete', level: levelVal } };
      break;
    case 'spiffs_list':
      payload = { spiffs: { command: 'list' } };
      break;
    case 'spiffs_read':
      if (!pathVal) {
        setControlFeedback('请输入路径。', true);
        return;
      }
      payload = { spiffs: { command: 'read', path: pathVal } };
      if (limitVal !== undefined) payload.spiffs.limit = limitVal;
      break;
    case 'spiffs_delete':
      if (!pathVal) {
        setControlFeedback('请输入路径。', true);
        return;
      }
      payload = { spiffs: { command: 'delete', path: pathVal } };
      break;
    case 'spiffs_write': {
      if (!pathVal) {
        setControlFeedback('请输入路径。', true);
        return;
      }
      let dataB64 = '';
      if (fileObj) {
        try {
          dataB64 = await readFileAsBase64(fileObj);
        } catch (err) {
          setControlFeedback(`读取文件失败: ${err}`, true);
          return;
        }
      } else if (writeText) {
        dataB64 = btoa(unescape(encodeURIComponent(writeText)));
      } else {
        setControlFeedback('请上传文件或填写写入文本。', true);
        return;
      }
      payload = { spiffs: { command: 'write', path: pathVal, data_base64: dataB64 } };
      break;
    }
    default:
      setControlFeedback('未支持的命令。', true);
      return;
  }

  if (port !== undefined) {
    payload.port = port;
  }

  const body = {
    dn,
    payload,
  };
  if (targetIp) body.target_ip = targetIp;

  setControlFeedback('发送中...', false);
  try {
    const resp = await fetchJSON('/api/config/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    setControlFeedback(`命令 ${resp.command_id || ''} 已下发。`, false);
    loadResults();
  } catch (error) {
    setControlFeedback(`发送失败: ${error.message}`, true);
  }
}
