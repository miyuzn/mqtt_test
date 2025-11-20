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

const state = {
  devices: [],
  results: [],
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

const normalizeMac = (value = '') => (value || '').replace(/[^0-9a-fA-F]/g, '').toUpperCase();

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
    deviceSelect.appendChild(option);
  });

  if (selectedDn) {
    const exists = Array.from(deviceSelect.options).some((option) => option.value === selectedDn);
    if (exists) {
      deviceSelect.value = selectedDn;
    }
  }
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
    const isOk = replyStatus === 'ok';
    const statusClass = isOk ? 'status-ok' : 'status-error';
    const detail = isOk ? JSON.stringify(item.reply || {}) : item.error || JSON.stringify(item.reply || {});
    const statusLabel = isOk ? 'ok' : 'error';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="font-mono">${formatDateTime(item.timestamp)}</span></td>
      <td><code>${item.dn || ''}</code></td>
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
    deviceMeta.textContent = state.devices.length ? `${state.devices.length} devices online` : 'No device selected';
    return;
  }
  const ip = option.dataset.ip;
  const lastSeen = option.dataset.lastSeen;
  const heartbeat = lastSeen ? `Last heartbeat: ${formatDateTime(lastSeen)}` : 'Last heartbeat: unknown';
  deviceMeta.textContent = ip ? `${ip} | ${heartbeat}` : heartbeat;
}

async function loadDevices() {
  const selectedDn = deviceSelect.value;
  deviceMeta.textContent = 'Loading devices...';
  try {
    const data = await fetchJSON('/api/devices');
    state.devices = data.items || [];
    renderDeviceOptions(selectedDn);
    renderDeviceTable();
    updateMetrics();
    updateDeviceMeta(deviceSelect.selectedOptions[0]);
    syncLicenseInputsFromDevice();
  } catch (error) {
    deviceMeta.textContent = error.message;
  }
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
  const dn = (licenseDnInput?.value || deviceSelect.value || '').trim().toUpperCase();
  const mac = normalizeMac((licenseMacInput?.value || dn || '').trim());
  const days = Number(licenseDaysInput?.value || licenseDefaults.days || 0);
  const tier = (licenseTierSelect?.value || licenseDefaults.tier || 'basic').trim().toLowerCase();
  let targetIp = (licenseIpInput?.value || '').trim();
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
  const dn = (licenseDnInput?.value || deviceSelect.value || '').trim().toUpperCase();
  let targetIp = (licenseIpInput?.value || '').trim();
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
}

async function handleSubmit(event) {
  event.preventDefault();
  const dn = deviceSelect.value;
  const model = (modelSelect && modelSelect.value) || DEFAULT_MODEL;
  if (!dn) {
    setFormFeedback('Please select a device before sending.', true);
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

  setFormFeedback('Sending command...', false);
  try {
    const resp = await fetchJSON('/api/config/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    setFormFeedback(`Command ${resp.command_id} sent.`, false);
    loadResults();
  } catch (error) {
    setFormFeedback(`Failed to send: ${error.message}`, true);
  }
}

function clearForm() {
  deviceSelect.value = '';
  analogInput.value = '';
  selectInput.value = '';
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
  if (licenseForm) {
    licenseForm.addEventListener('submit', handleLicenseSubmit);
  }
  if (licenseQueryBtn) {
    licenseQueryBtn.addEventListener('click', handleLicenseQuery);
  }
  if (licenseForm && licenseDefaults && licenseDefaults.enabled === false) {
    Array.from(licenseForm.elements).forEach((el) => {
      if (el.id !== 'license-output') el.disabled = true;
    });
    setLicenseFeedback('License 服务未启用。', true);
  }
  loadDevices();
  loadResults();
  setInterval(loadDevices, 8000);
  setInterval(loadResults, 8000);
}

init();


