const ANALOG_PRESETS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
const SELECT_PRESETS = [32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44];
const API_BASE = "";

const deviceSelect = document.getElementById("device-select");
const refreshBtn = document.getElementById("refresh-devices");
const dnInput = document.getElementById("dn-input");
const ipInput = document.getElementById("ip-input");
const deviceMeta = document.getElementById("device-meta");
const analogInput = document.getElementById("analog-input");
const selectInput = document.getElementById("select-input");
const form = document.getElementById("config-form");
const resultOutput = document.getElementById("result-output");
const clearBtn = document.getElementById("clear-form");

const state = {
  devices: [],
};

function renderPinButtons(containerId, pins, targetInput) {
  const container = document.getElementById(containerId);
  if (!container) {
    console.warn(`未找到 ${containerId} 容器，跳过渲染`);
    return;
  }
  container.innerHTML = "";
  pins.forEach((pin) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pin-btn";
    btn.textContent = pin;
    btn.dataset.pin = pin;
    btn.dataset.target = targetInput;
    btn.addEventListener("click", onPinButtonClick);
    container.appendChild(btn);
  });
}

function parsePins(value) {
  return Array.from(
    new Set(
      value
        .split(/[^0-9]+/)
        .map((v) => v.trim())
        .filter(Boolean)
        .map((v) => Number(v))
        .filter((n) => !Number.isNaN(n))
    )
  );
}

function syncPinButtons(targetInputId) {
  const input = document.getElementById(targetInputId);
  if (!input) {
    return;
  }
  const pins = parsePins(input.value);
  document
    .querySelectorAll(`.pin-btn[data-target="${targetInputId}"]`)
    .forEach((btn) => {
      const value = Number(btn.dataset.pin);
      btn.setAttribute("aria-pressed", pins.includes(value));
    });
}

function onPinButtonClick(event) {
  const btn = event.currentTarget;
  const input = document.getElementById(btn.dataset.target);
  const value = Number(btn.dataset.pin);
  const pins = parsePins(input.value);
  const index = pins.indexOf(value);
  if (index >= 0) {
    pins.splice(index, 1);
  } else {
    pins.push(value);
  }
  input.value = pins.join(",");
  syncPinButtons(btn.dataset.target);
}

async function loadDevices() {
  deviceMeta.textContent = "加载中...";
  try {
    const response = await fetch(`${API_BASE}/api/devices`);
    if (!response.ok) {
      throw new Error(`加载失败：${response.status}`);
    }
    const data = await response.json();
    state.devices = data.items ?? [];
    renderDeviceOptions();
    deviceMeta.textContent = `共 ${state.devices.length} 台在线`;
  } catch (error) {
    console.error(error);
    deviceMeta.textContent = error.message;
  }
}

function renderDeviceOptions() {
  deviceSelect.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "请选择设备";
  deviceSelect.appendChild(placeholder);

  state.devices.forEach((device) => {
    const option = document.createElement("option");
    option.value = device.dn;
    option.textContent = device.ip ? `${device.dn} (${device.ip})` : device.dn;
    option.dataset.ip = device.ip ?? "";
    option.dataset.lastSeen = device.last_seen;
    deviceSelect.appendChild(option);
  });
}

function onDeviceChange() {
  const selected = deviceSelect.selectedOptions[0];
  if (!selected || !selected.value) {
    dnInput.value = "";
    ipInput.value = "";
    deviceMeta.textContent = "未选择设备";
    return;
  }
  dnInput.value = selected.value;
  ipInput.value = selected.dataset.ip || "";
  const lastSeen = selected.dataset.lastSeen;
  deviceMeta.textContent = lastSeen
    ? `最近心跳：${new Date(lastSeen).toLocaleString()}`
    : "未知心跳";
}

async function handleSubmit(event) {
  event.preventDefault();
  const dn = dnInput.value.trim();
  if (!dn) {
    resultOutput.textContent = "请先选择或输入 DN";
    return;
  }
  const payload = {
    dn,
    ip: ipInput.value.trim() || undefined,
    analog: parsePins(analogInput.value),
    select: parsePins(selectInput.value),
  };

  try {
    const response = await fetch(`${API_BASE}/api/config/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || "下发失败");
    }
    resultOutput.textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    resultOutput.textContent = error.message;
  }
}

function clearForm() {
  dnInput.value = "";
  ipInput.value = "";
  analogInput.value = "";
  selectInput.value = "";
  resultOutput.textContent = "已清空，等待下发";
  syncPinButtons("analog-input");
  syncPinButtons("select-input");
}

function debounce(fn, wait = 300) {
  let timer;
  return function debounced(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), wait);
  };
}

function init() {
  const required = [
    ["deviceSelect", deviceSelect],
    ["refreshBtn", refreshBtn],
    ["dnInput", dnInput],
    ["ipInput", ipInput],
    ["deviceMeta", deviceMeta],
    ["analogInput", analogInput],
    ["selectInput", selectInput],
    ["form", form],
    ["clearBtn", clearBtn],
    ["resultOutput", resultOutput],
  ];
  const missing = required.filter(([, el]) => !el).map(([name]) => name);
  if (missing.length) {
    console.error(`页面缺少必要元素：${missing.join(", ")}`);
    return;
  }

  renderPinButtons("analog-grid", ANALOG_PRESETS, "analog-input");
  renderPinButtons("select-grid", SELECT_PRESETS, "select-input");
  syncPinButtons("analog-input");
  syncPinButtons("select-input");
  loadDevices();

  deviceSelect.addEventListener("change", onDeviceChange);
  refreshBtn.addEventListener("click", loadDevices);
  form.addEventListener("submit", handleSubmit);
  clearBtn.addEventListener("click", clearForm);
  analogInput.addEventListener(
    "input",
    debounce(() => syncPinButtons("analog-input"))
  );
  selectInput.addEventListener(
    "input",
    debounce(() => syncPinButtons("select-input"))
  );
}

init();
