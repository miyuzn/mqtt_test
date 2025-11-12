(function () {
  const alertBox = document.getElementById('configAlert');
  const devicesTable = document.querySelector('#devicesTable tbody');
  const resultsTable = document.querySelector('#resultsTable tbody');
  const form = document.getElementById('configForm');

  const notify = (type, message) => {
    if (!alertBox) return;
    alertBox.classList.remove('d-none', 'alert-success', 'alert-danger', 'alert-warning', 'alert-info');
    alertBox.classList.add(`alert-${type}`);
    alertBox.textContent = message;
  };

  const fetchJSON = async (url, options = {}) => {
    const resp = await fetch(url, options);
    if (!resp.ok) {
      const detail = await resp.json().catch(() => ({}));
      throw new Error(detail.detail || detail.error || resp.statusText);
    }
    return resp.json();
  };

  const renderDevices = (items) => {
    devicesTable.innerHTML = '';
    if (!items || items.length === 0) {
      devicesTable.innerHTML = '<tr><td colspan="4" class="text-muted text-center">暂无设备</td></tr>';
      return;
    }
    items.forEach((item) => {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="font-monospace">${item.dn || ''}</td>
        <td>${item.ip || '-'}</td>
        <td>${item.agent_id || '-'}</td>
        <td>${item.last_seen || '-'}</td>
      `;
      tr.addEventListener('click', () => {
        document.getElementById('inputDn').value = item.dn || '';
      });
      devicesTable.appendChild(tr);
    });
  };

  const renderResults = (items) => {
    resultsTable.innerHTML = '';
    if (!items || items.length === 0) {
      resultsTable.innerHTML = '<tr><td colspan="5" class="text-muted text-center">暂无记录</td></tr>';
      return;
    }
    items.forEach((item) => {
      const statusClass = item.status === 'ok' ? 'text-success' : 'text-danger';
      const replyText = item.reply ? JSON.stringify(item.reply) : item.error || '';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="font-monospace small">${item.timestamp || ''}</td>
        <td class="font-monospace">${item.dn || ''}</td>
        <td class="${statusClass}">${item.status || '-'}</td>
        <td>${item.agent_id || ''}</td>
        <td><code class="small">${replyText}</code></td>
      `;
      resultsTable.appendChild(tr);
    });
  };

  const refreshDevices = async () => {
    try {
      const data = await fetchJSON('/api/devices');
      renderDevices(data.items || []);
    } catch (err) {
      notify('danger', `获取设备列表失败：${err.message}`);
    }
  };

  const refreshResults = async () => {
    try {
      const data = await fetchJSON('/api/commands/latest');
      renderResults(data.items || []);
    } catch (err) {
      notify('danger', `获取结果失败：${err.message}`);
    }
  };

  const parsePins = (value) => {
    if (!value) return [];
    return value
      .split(/[,\n]/)
      .map((item) => item.trim())
      .filter(Boolean)
      .map((token) => Number(token))
      .filter((num) => Number.isFinite(num));
  };

  document.getElementById('refreshDevices')?.addEventListener('click', () => {
    refreshDevices();
  });
  document.getElementById('refreshResults')?.addEventListener('click', () => {
    refreshResults();
  });

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const body = {
      dn: formData.get('dn'),
      requested_by: formData.get('requested_by') || undefined,
      analog: parsePins(formData.get('analog')),
      select: parsePins(formData.get('select')),
    };
    if (!body.analog.length || !body.select.length) {
      notify('warning', '请填写 analog 与 select 列表');
      return;
    }
    try {
      const resp = await fetchJSON('/api/config/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      notify('success', `命令 ${resp.command_id} 已发送`);
      refreshResults();
    } catch (err) {
      notify('danger', `发送失败：${err.message}`);
    }
  });

  refreshDevices();
  refreshResults();
  setInterval(refreshDevices, 5000);
  setInterval(refreshResults, 5000);
})();
