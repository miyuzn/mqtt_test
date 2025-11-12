const ANALOG_PRESETS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
const SELECT_PRESETS = [32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44];
const API_BASE = '';

const deviceSelect = document.getElementById('device-select');
const refreshDevicesBtn = document.getElementById('refresh-devices');
const refreshResultsBtn = document.getElementById('refresh-results');
const dnInput = document.getElementById('dn-input');
const ipInput = document.getElementById('ip-input');
const operatorInput = document.getElementById('operator-input');
const deviceMeta = document.getElementById('device-meta');
const analogInput = document.getElementById('analog-input');
const selectInput = document.getElementById('select-input');
const deviceCountEl = document.getElementById('device-count');
const agentCountEl = document.getElementById('agent-count');
const resultOutput = document.getElementById('result-output');
const form = document.getElementById('config-form');
const clearBtn = document.getElementById('clear-form');
const devicesTableBody = document.getElementById('devices-table-body');
const historyTableBody = document.getElementById('history-table-body');

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

function renderDeviceOptions() {
  deviceSelect.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = '请选择设备';
  deviceSelect.appendChild(placeholder);

  state.devices.forEach((device) => {
    const option = document.createElement('option');
    option.value = device.dn;
    option.textContent = device.ip ? `${device.dn} (${device.ip})` : device.dn;
    option.dataset.ip = device.ip || '';
    option.dataset.lastSeen = device.last_seen || '';
    option.dataset.agent = device.agent_id || '';
    deviceSelect.appendChild(option);
  });
}

function renderDeviceTable() {
  devicesTableBody.innerHTML = '';
  if (!state.devices.length) {
    devicesTableBody.innerHTML = '<tr><td colspan="4" class="table-empty">暂无数据</td></tr>';
    return;
  }
  state.devices.forEach((item) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><code>${item.dn || ''}</code></td>
      <td>${item.ip || '-'}</td>
      <td>${item.agent_id || '-'}</td>
      <td>${item.last_seen || '-'}</td>
    `;
    tr.addEventListener('click', () => {
      dnInput.value = item.dn || '';
      ipInput.value = item.ip || '';
    });
    devicesTableBody.appendChild(tr);
  });
}

function renderHistoryTable() {
  historyTableBody.innerHTML = '';
  if (!state.results.length) {
    historyTableBody.innerHTML = '<tr><td colspan="5" class="table-empty">暂无数据</td></tr>';
    return;
  }
  state.results.forEach((item) => {
    const statusClass = item.status === 'ok' ? 'status-ok' : 'status-error';
    const detail = item.status === 'ok'
      ? JSON.stringify(item.reply || {})
      : item.error || '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="font-mono">${item.timestamp || ''}</span></td>
      <td><code>${item.dn || ''}</code></td>
      <td class="${statusClass}">${item.status || '-'}</td>
      <td>${item.agent_id || '-'}</td>
      <td><code>${detail}</code></td>
    `;
    historyTableBody.appendChild(tr);
  });
}

function updateMetrics() {
  deviceCountEl.textContent = `设备：${state.devices.length}`;
  const agents = new Set(state.devices.map((item) => item.agent_id).filter(Boolean));
  agentCountEl.textContent = `发送端：${agents.size || '--'}`;
}

async function loadDevices() {
  deviceMeta.textContent = '加载中...';
  try {
    const data = await fetchJSON('/api/devices');
    state.devices = data.items || [];
    renderDeviceOptions();
    renderDeviceTable();
    updateMetrics();
    deviceMeta.textContent = `共 ${state.devices.length} 台在线`;
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
    resultOutput.textContent = `结果拉取失败：${error.message}`;
  }
}

function onDeviceChange() {
  const option = deviceSelect.selectedOptions[0];
  if (!option || !option.value) {
    dnInput.value = '';
    ipInput.value = '';
    deviceMeta.textContent = '未选择设备';
    return;
  }
  dnInput.value = option.value;
  ipInput.value = option.dataset.ip || '';
  const lastSeen = option.dataset.lastSeen;
  deviceMeta.textContent = lastSeen ? `最近心跳：${new Date(lastSeen).toLocaleString()}` : '未知心跳';
}

async function handleSubmit(event) {
  event.preventDefault();
  const dn = dnInput.value.trim();
  if (!dn) {
    resultOutput.textContent = '请先选择或输入 DN';
    return;
  }
  const analogPins = parsePins(analogInput.value);
  const selectPins = parsePins(selectInput.value);
  if (!analogPins.length || !selectPins.length) {
    resultOutput.textContent = 'analog / select 不能为空';
    return;
  }
  const payload = {
    dn,
    analog: analogPins,
    select: selectPins,
  };
  if (operatorInput.value.trim()) {
    payload.requested_by = operatorInput.value.trim();
  }
  if (ipInput.value.trim()) {
    payload.target_ip = ipInput.value.trim();
  }

  resultOutput.textContent = '下发中...';
  try {
    const resp = await fetchJSON('/api/config/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    resultOutput.textContent = `命令 ${resp.command_id} 已发送\n` + JSON.stringify(resp, null, 2);
    loadResults();
  } catch (error) {
    resultOutput.textContent = `发送失败：${error.message}`;
  }
}

function clearForm() {
  dnInput.value = '';
  ipInput.value = '';
  operatorInput.value = '';
  analogInput.value = '';
  selectInput.value = '';
  resultOutput.textContent = '尚未下发';
  syncPinButtons('analog-input');
  syncPinButtons('select-input');
}

function debounce(fn, wait = 300) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(null, args), wait);
  };
}

function init() {
  renderPinButtons('analog-grid', ANALOG_PRESETS, 'analog-input');
  renderPinButtons('select-grid', SELECT_PRESETS, 'select-input');
  syncPinButtons('analog-input');
  syncPinButtons('select-input');
  deviceSelect.addEventListener('change', onDeviceChange);
  refreshDevicesBtn.addEventListener('click', () => loadDevices());
  refreshResultsBtn.addEventListener('click', () => loadResults());
  form.addEventListener('submit', handleSubmit);
  clearBtn.addEventListener('click', clearForm);
  analogInput.addEventListener(
    'input',
    debounce(() => syncPinButtons('analog-input'))
  );
  selectInput.addEventListener(
    'input',
    debounce(() => syncPinButtons('select-input'))
  );
  loadDevices();
  loadResults();
  setInterval(loadDevices, 8000);
  setInterval(loadResults, 8000);
}

init();
