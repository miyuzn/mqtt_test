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
const controlLicenseMacInput = document.getElementById('control-license-mac');
const controlLicenseDaysInput = document.getElementById('control-license-days');
const controlLicenseTierSelect = document.getElementById('control-license-tier');
const controlLicensePortInput = document.getElementById('control-license-port');
const controlLicenseIpInput = document.getElementById('control-license-ip');
const controlLogLevelSelect = document.getElementById('control-log-level');
const debugLogContent = document.getElementById('debug-log-content');
const clearDebugLogBtn = document.getElementById('clear-debug-log');

const state = {
  devices: [],
  results: [],
  discovery: {
    broadcast: [],
  },
};

function truncateBase64(data) {
  if (typeof data === 'string') {
    if (data.length > 200 && !data.includes(' ')) {
      return `<base64 data length=${data.length}>`;
    }
    return data;
  }
  if (Array.isArray(data)) {
    return data.map(truncateBase64);
  }
  if (typeof data === 'object' && data !== null) {
    const copy = {};
    for (const key of Object.keys(data)) {
      if (key === 'data_base64' && typeof data[key] === 'string') {
        copy[key] = `<base64 data length=${data[key].length}>`;
      } else {
        copy[key] = truncateBase64(data[key]);
      }
    }
    return copy;
  }
  return data;
}

function logDebugJson(label, data) {
  if (!debugLogContent) return;
  const ts = new Date().toISOString().split('T')[1].slice(0, -1); // HH:MM:SS.mmm
  const safeData = truncateBase64(data);
  const jsonStr = JSON.stringify(safeData, null, 2);
  const entry = `[${ts}] ${label}:
${jsonStr}

`;
  debugLogContent.textContent = entry + debugLogContent.textContent;
}

const fetchJSON = async (path, options = {}) => {
  const resp = await fetch(`${API_BASE}${path}`, options);
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error(detail.detail || detail.error || resp.statusText);
  }
  return resp.json();
};

function reorderLogBytes(dataUint8, offset) {
  if (!dataUint8 || !dataUint8.length) return dataUint8;
  if (offset <= 0 || offset >= dataUint8.length) {
    let end = dataUint8.length;
    while (end > 0 && dataUint8[end - 1] === 0) end--;
    return dataUint8.subarray(0, end);
  }
  const tail = dataUint8.subarray(offset);
  const head = dataUint8.subarray(0, offset);
  
  const ordered = new Uint8Array(dataUint8.length);
  ordered.set(tail, 0);
  ordered.set(head, tail.length);
  
  let end = ordered.length;
  while (end > 0 && ordered[end - 1] === 0) end--;
  return ordered.subarray(0, end);
}

function triggerDownload(dataUint8, filename) {
  const blob = new Blob([dataUint8], { type: 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function extractLastLogLine(dataUint8) {
  try {
    const decoder = new TextDecoder('utf-8');
    const text = decoder.decode(dataUint8);
    const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    if (lines.length > 0) {
      return lines[lines.length - 1];
    }
    return '(log is empty)';
  } catch (err) {
    return `(parse failed: ${err.message})`;
  }
}

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

const setControlFeedback = (message = '', isError = false) => {
  if (!controlFeedback) return;
  controlFeedback.textContent = message;
  controlFeedback.dataset.state = isError ? 'error' : 'info';
};

const normalizeMac = (value = '') => (value || '').replace(/[^0-9a-fA-F]/g, '').toUpperCase();
const normalizeDn = (value = '') => (value || '').replace(/[^0-9a-fA-F]/g, '').toUpperCase();

const applyLicenseDefaults = () => {
  const defaults = licenseDefaults || {};
  const portVal = Number(defaults.port || 0);
  const daysVal = Number(defaults.days || 0);
  if (controlLicenseDaysInput && daysVal > 0) {
    controlLicenseDaysInput.value = daysVal;
  }
  if (controlLicenseTierSelect && defaults.tier) {
    controlLicenseTierSelect.value = defaults.tier;
  }
  if (controlLicensePortInput && portVal > 0) {
    controlLicensePortInput.value = portVal;
  }
};

function syncLicenseInputsFromDevice() {
  if (!deviceSelect) return;
  const option = deviceSelect.selectedOptions[0];
  if (!option) return;
  const dn = option.value || '';
  const ip = option.dataset.ip || '';
  if (controlLicenseMacInput && (!controlLicenseMacInput.value || controlLicenseMacInput.dataset.autoFilled === '1')) {
    controlLicenseMacInput.value = dn;
    controlLicenseMacInput.dataset.autoFilled = '1';
  }
  if (controlLicenseIpInput && (!controlLicenseIpInput.value || controlLicenseIpInput.dataset.autoFilled === '1')) {
    controlLicenseIpInput.value = ip;
    controlLicenseIpInput.dataset.autoFilled = '1';
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
  if (controlLicenseIpInput && (!controlLicenseIpInput.value || controlLicenseIpInput.dataset.autoFilled === '1')) {
    controlLicenseIpInput.value = ip;
    controlLicenseIpInput.dataset.autoFilled = '1';
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
  state.results.forEach((item, index) => {
    const replyStatus = (item.reply && item.reply.status) ? String(item.reply.status).toLowerCase() : '';
    const overallStatus = (item.status || replyStatus || '').toLowerCase();
    const isOk = overallStatus ? overallStatus === 'ok' : replyStatus === 'ok';
    const statusClass = isOk ? 'status-ok' : 'status-error';
    
    const safeItem = truncateBase64(item);
    
    const detailPayload = safeItem.error || safeItem.reply || safeItem.payload || {};
    const detail = typeof detailPayload === 'string' ? detailPayload : JSON.stringify(detailPayload || {});
    const statusLabel = overallStatus || replyStatus || (isOk ? 'ok' : 'error');
    const payloadType = item.payload && item.payload.type ? String(item.payload.type).toLowerCase() : '';
    const dnLabel = (payloadType === 'discover' || item.method === 'discover' || (item.dn || '').toUpperCase() === 'BROADCAST')
      ? 'broadcast'
      : (item.dn || '');

    let extraHtml = '';
    if (item.reply && typeof item.reply.data_base64 === 'string') {
      const b64 = item.reply.data_base64;
      const approxBytes = Math.round((b64.length * 3) / 4);
      extraHtml = `<button class="ghost-btn download-btn" data-index="${index}" style="padding: 2px 8px; font-size: 0.8rem; margin-left: 8px;">Download (${approxBytes} B)</button>`;
    }

    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="font-mono">${formatDateTime(item.timestamp)}</span></td>
      <td><code>${dnLabel}</code></td>
      <td class="${statusClass}">${statusLabel}</td>
      <td>
        <div style="display: flex; align-items: center; gap: 8px;">
          <code style="flex: 1;">${detail}</code>
          ${extraHtml}
        </div>
      </td>
    `;
    
    if (extraHtml) {
      const btn = tr.querySelector('.download-btn');
      if (btn) {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const idx = parseInt(e.target.dataset.index, 10);
          const dataItem = state.results[idx];
          if (dataItem && dataItem.reply && dataItem.reply.data_base64) {
            try {
              const b64 = dataItem.reply.data_base64;
              const binStr = atob(b64);
              const bytes = new Uint8Array(binStr.length);
              for (let i = 0; i < binStr.length; i++) bytes[i] = binStr.charCodeAt(i);
              
              let fname = 'download.bin';
              if (dataItem.payload && dataItem.payload.spiffs && dataItem.payload.spiffs.path) {
                 fname = dataItem.payload.spiffs.path.split('/').pop();
              } else if (dataItem.payload && dataItem.payload.log) {
                 fname = 'log.txt';
              }
              triggerDownload(bytes, fname);
            } catch (err) {
              alert(`Download failed: ${err.message}`);
            }
          }
        });
      }
    }

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

async function loadDevices(withDiscover = false) {
  const selectedDn = deviceSelect.value || normalizeDn(manualDnInput?.value || '');
  if (withDiscover) {
    deviceMeta.textContent = 'Sending broadcast discover...';
    try {
      const body = {};
      logDebugJson('Discover Broadcast', body);
      await fetchJSON('/api/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (error) {
      deviceMeta.textContent = `Failed to queue discover: ${error.message}`;
    }
  } else {
    deviceMeta.textContent = 'Loading devices...';
  }
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
    logDebugJson('Config Apply', body);
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
  if (controlLicenseIpInput) {
    controlLicenseIpInput.value = '';
    controlLicenseIpInput.dataset.autoFilled = '0';
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

function updateControlVisibility(action) {
  const visible = new Set();
  switch (action) {
    case 'filter_set':
      visible.add('control-filter');
      visible.add('control-port');
      break;
    case 'calib_collect':
      visible.add('control-calib');
      visible.add('control-level');
      visible.add('control-port');
      break;
    case 'calib_all':
      visible.add('control-level');
      visible.add('control-calib'); // for start/duration
      visible.add('control-port');
      break;
    case 'calib_level_query':
    case 'calib_level_delete':
      visible.add('control-level');
      visible.add('control-port');
      break;
    case 'spiffs_read':
      visible.add('control-path');
      visible.add('control-limit');
      visible.add('control-port');
      break;
    case 'spiffs_write':
      visible.add('control-path');
      visible.add('control-write');
      visible.add('control-port');
      break;
    case 'spiffs_delete':
      visible.add('control-path');
      visible.add('control-port');
      break;
    case 'spiffs_list':
      visible.add('control-port');
      break;
    case 'license_apply':
      visible.add('control-license-mac');
      visible.add('control-license-apply');
      visible.add('control-license-port');
      visible.add('control-license-ip');
      break;
    case 'license_query':
      visible.add('control-license-mac');
      visible.add('control-license-port');
      visible.add('control-license-ip');
      break;
    case 'log_enable':
      visible.add('control-log');
      visible.add('control-port');
      break;
    case 'log_disable':
    case 'log_status':
      visible.add('control-port');
      break;
    case 'log_download':
      visible.add('control-port');
      break;
    case 'filter_query':
    case 'standby_enable':
    case 'standby_disable':
    case 'calib_enable':
    case 'calib_disable':
    case 'calib_status':
    default:
      break;
  }
  document.querySelectorAll('.control-field').forEach((field) => {
    const fieldClasses = Array.from(field.classList).filter((cls) => cls.startsWith('control-'));
    const shouldShow = fieldClasses.some((cls) => visible.has(cls));
    field.classList.toggle('hidden', !shouldShow);
  });
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
  refreshDevicesBtn.addEventListener('click', () => loadDevices(true));
  refreshResultsBtn.addEventListener('click', () => loadResults());
  form.addEventListener('submit', handleSubmit);
  clearBtn.addEventListener('click', clearForm);
  if (controlLicenseMacInput) {
    controlLicenseMacInput.addEventListener('input', () => {
      controlLicenseMacInput.dataset.autoFilled = '0';
    });
  }
  if (controlLicenseIpInput) {
    controlLicenseIpInput.addEventListener('input', () => {
      controlLicenseIpInput.dataset.autoFilled = '0';
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
  if (controlPathInput) {
    controlPathInput.addEventListener('input', () => {
      if (/[\/\\]/.test(controlPathInput.value)) {
        controlPathInput.value = controlPathInput.value.replace(/[\/\\]/g, '');
        setControlFeedback('Slashes and backslashes are not allowed in path.', true);
      }
    });
  }
  if (controlForm) {
    controlForm.addEventListener('submit', handleControlSubmit);
    controlAction.addEventListener('change', () => updateControlVisibility(controlAction.value));
    updateControlVisibility(controlAction.value);
  }
  if (clearDebugLogBtn) {
    clearDebugLogBtn.addEventListener('click', () => {
      if (debugLogContent) debugLogContent.textContent = '';
    });
  }
  loadDevices(true);
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
    setControlFeedback('Please select a device or enter DN/MAC first.', true);
    return;
  }
  const action = controlAction?.value || '';
  if (!action) {
    setControlFeedback('Please choose a command.', true);
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
  let pathVal = (controlPathInput?.value || '').trim();
  if (/[\/\\]/.test(pathVal)) {
    setControlFeedback('Path cannot contain / or \\ characters.', true);
    return;
  }
  const limitVal = getNumeric(controlLimitInput);
  const enabledChecked = controlEnabledCheckbox?.checked;
  const writeText = controlWriteText?.value || '';
  const fileObj = controlFileInput?.files?.[0];
  const licenseMacVal = normalizeMac((controlLicenseMacInput?.value || dn || '').trim());
  const licenseDaysVal = getNumeric(controlLicenseDaysInput) || Number(licenseDefaults.days || 0) || undefined;
  const licenseTierVal = (controlLicenseTierSelect?.value || licenseDefaults.tier || 'basic').trim().toLowerCase();
  const licensePortVal = getNumeric(controlLicensePortInput) || Number(licenseDefaults.port || 0) || undefined;
  let licenseTargetIp = (controlLicenseIpInput?.value || targetIp || '').trim();
  const logLevelVal = controlLogLevelSelect?.value || 'info';

  const doSend = async (body) => {
    if (targetIp) body.target_ip = targetIp;
    if (port !== undefined && !body.payload.port) body.payload.port = port;
    logDebugJson('Control Command', body);
    return fetchJSON('/api/config/control', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  };

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
        setControlFeedback('AnalogPin / SelectPin / level are required.', true);
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
    case 'calib_all':
      if (!levelVal) {
        setControlFeedback('Calibration level is required.', true);
        return;
      }
      payload = {
        calibration: {
          command: 'calibrate_all',
          level: Number(levelVal),
          start_time: startTimeVal ?? 1000,
          calibration_time: calibTimeVal ?? 5000,
        },
      };
      break;
    case 'calib_level_query':
      if (!levelVal) {
        setControlFeedback('Please provide level.', true);
        return;
      }
      payload = { calibration: { command: 'level', level: levelVal } };
      break;
    case 'calib_level_delete':
      if (!levelVal) {
        setControlFeedback('Please provide level.', true);
        return;
      }
      payload = { calibration: { command: 'delete', level: levelVal } };
      break;
    case 'spiffs_list':
      payload = { spiffs: { command: 'list' } };
      break;
    case 'spiffs_read': {
      if (!pathVal) {
        setControlFeedback('Please provide a path.', true);
        return;
      }
      payload = { spiffs: { command: 'read', path: pathVal } };
      if (limitVal !== undefined) payload.spiffs.limit = limitVal;
      
      setControlFeedback('Reading file...', false);
      try {
        const resp = await doSend({ dn, payload });
        if (resp.reply && resp.reply.data_base64) {
          const binaryString = atob(resp.reply.data_base64);
          const bytes = new Uint8Array(binaryString.length);
          for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
          }
          const fname = pathVal.split('/').pop() || 'download.bin';
          triggerDownload(bytes, fname);
          setControlFeedback(`Read success. Downloaded ${bytes.length} bytes as ${fname}.`, false);
        } else {
          setControlFeedback(`Read command queued.`, false);
        }
        loadResults();
      } catch (err) {
        setControlFeedback(`Read failed: ${err.message}`, true);
      }
      return;
    }
    case 'spiffs_delete':
      if (!pathVal) {
        setControlFeedback('Please provide a path.', true);
        return;
      }
      payload = { spiffs: { command: 'delete', path: pathVal } };
      break;
    case 'spiffs_write': {
      if (!pathVal) {
        setControlFeedback('Please provide a path.', true);
        return;
      }
      let dataB64 = '';
      if (fileObj) {
        try {
          dataB64 = await readFileAsBase64(fileObj);
        } catch (err) {
          setControlFeedback(`Failed to read file: ${err}`, true);
          return;
        }
      } else if (writeText) {
        dataB64 = btoa(unescape(encodeURIComponent(writeText)));
      } else {
        setControlFeedback('Upload a file or provide text to write.', true);
        return;
      }
      payload = { spiffs: { command: 'write', path: pathVal, data_base64: dataB64 } };
      break;
    }
    case 'log_status':
      payload = { log: { command: 'status' } };
      break;
    case 'log_enable':
      payload = { log: { command: 'enable', level: logLevelVal } };
      break;
    case 'log_disable':
      payload = { log: { command: 'disable' } };
      break;
    case 'log_download': {
      setControlFeedback('Downloading log (ordered by device)...', false);
      payload = { log: { command: 'read' } };

      try {
        const resp = await doSend({ dn, payload });
        if (resp.reply && resp.reply.data_base64) {
          const binaryString = atob(resp.reply.data_base64);
          const bytes = new Uint8Array(binaryString.length);
          for (let i = 0; i < binaryString.length; i++) {
            bytes[i] = binaryString.charCodeAt(i);
          }
          triggerDownload(bytes, 'log.txt');
          setControlFeedback(`Log downloaded (${bytes.length} bytes).`, false);
        } else {
          setControlFeedback(`Log read command queued.`, false);
        }
        loadResults();
      } catch (err) {
        setControlFeedback(`Log download failed: ${err.message}`, true);
      }
      return;
    }

    case 'license_apply': {
      if (!licenseMacVal || licenseMacVal.length !== 12) {
        setControlFeedback('Device code (MAC) must be 12 hex characters.', true);
        return;
      }
      if (!licenseDaysVal || licenseDaysVal <= 0) {
        setControlFeedback('License days must be a positive integer.', true);
        return;
      }
      const body = {
        dn,
        device_code: licenseMacVal,
        days: Math.floor(licenseDaysVal),
        tier: licenseTierVal || 'basic',
      };
      if (licenseTargetIp) body.target_ip = licenseTargetIp;
      if (licensePortVal && licensePortVal > 0) body.port = Math.floor(licensePortVal);
      setControlFeedback('Sending license apply...', false);
      try {
        logDebugJson('License Apply', body);
        const resp = await fetchJSON('/api/license/apply', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        setControlFeedback(`License command ${resp.command_id || ''} queued.`, false);
        loadResults();
      } catch (error) {
        setControlFeedback(`License apply failed: ${error.message}`, true);
      }
      return;
    }
    case 'license_query': {
      if (!licenseMacVal || licenseMacVal.length !== 12) {
        setControlFeedback('Device code (MAC) must be 12 hex characters.', true);
        return;
      }
      if (!licenseTargetIp) {
        setControlFeedback('Target IP is required for license query.', true);
        return;
      }
      const qs = new URLSearchParams();
      qs.set('dn', dn);
      qs.set('target_ip', licenseTargetIp);
      if (licensePortVal && licensePortVal > 0) qs.set('port', Math.floor(licensePortVal));
      setControlFeedback('Sending license query...', false);
      try {
        logDebugJson('License Query', Object.fromEntries(qs.entries()));
        const resp = await fetchJSON(`/api/license/query?${qs.toString()}`);
        setControlFeedback(`License query ${resp.command_id || ''} queued.`, false);
        loadResults();
      } catch (error) {
        setControlFeedback(`License query failed: ${error.message}`, true);
      }
      return;
    }
    default:
      setControlFeedback('Unsupported action.', true);
      return;
  }

  if (port !== undefined) {
    payload.port = port;
  }

  const body = {
    dn,
    payload,
  };
  
  setControlFeedback('Sending...', false);
  try {
    const resp = await doSend(body);
    setControlFeedback(`Command ${resp.command_id || ''} queued.`, false);
    loadResults();
  } catch (error) {
    setControlFeedback(`Send failed: ${error.message}`, true);
  }
}