(function () {
  const MAX_POINTS = 50;
  const ctx = document.getElementById('pressureChart').getContext('2d');
  const pressureChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: '压力值',
          data: [],
          borderColor: '#0d6efd',
          backgroundColor: 'rgba(13, 110, 253, 0.1)',
          tension: 0.35,
        },
      ],
    },
    options: {
      animation: false,
      responsive: true,
      scales: {
        x: {
          type: 'time',
          time: {
            tooltipFormat: 'HH:mm:ss',
            displayFormats: {
              second: 'HH:mm:ss',
            },
          },
        },
        y: {
          title: {
            display: true,
            text: '压力',
          },
        },
      },
    },
  });

  const topicEl = document.getElementById('messageTopic');
  const payloadEl = document.getElementById('messagePayload');
  const timeEl = document.getElementById('messageTimestamp');
  const alertEl = document.getElementById('messageAlert');

  const socket = io();
  socket.on('mqtt_message', (msg) => {
    topicEl.textContent = msg.topic || '未知主题';
    payloadEl.textContent = msg.payload || '';
    timeEl.textContent = msg.timestamp || new Date().toISOString();

    if (msg.error) {
      alertEl.classList.remove('d-none', 'alert-info');
      alertEl.classList.add('alert-danger');
      alertEl.textContent = msg.error;
      return;
    }

    alertEl.classList.remove('alert-danger');
    alertEl.classList.add('alert-info');
    alertEl.textContent = '数据已更新';
    alertEl.classList.remove('d-none');

    if (typeof msg.pressure === 'number') {
      const parsedTime = msg.timestamp ? new Date(msg.timestamp) : new Date();
      pressureChart.data.labels.push(parsedTime);
      pressureChart.data.datasets[0].data.push({ x: parsedTime, y: msg.pressure });

      if (pressureChart.data.labels.length > MAX_POINTS) {
        pressureChart.data.labels.splice(0, pressureChart.data.labels.length - MAX_POINTS);
        pressureChart.data.datasets[0].data.splice(
          0,
          pressureChart.data.datasets[0].data.length - MAX_POINTS
        );
      }
      pressureChart.update('none');
    }
  });
})();
