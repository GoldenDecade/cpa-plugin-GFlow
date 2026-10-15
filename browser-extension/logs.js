// logs.js - GFlow 日志查看脚本
let loading = false;

function sendMessage(request) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(request, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}

function formatTime(isoString) {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return '时间未知';
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function renderLogs(logs) {
  const container = document.getElementById('logsContainer');
  container.replaceChildren();

  if (!Array.isArray(logs) || logs.length === 0) {
    container.innerHTML = '<div class="empty-state">暂无日志记录</div>';
    return;
  }

  const fragment = document.createDocumentFragment();
  for (const log of logs) {
    const level = ['INFO', 'SUCCESS', 'ERROR'].includes(log.level) ? log.level : 'INFO';
    const entry = document.createElement('div');
    entry.className = `log-entry ${level}`;

    const header = document.createElement('div');
    header.className = 'log-header';
    const levelEl = document.createElement('span');
    levelEl.className = `log-level ${level}`;
    levelEl.textContent = level;
    const timeEl = document.createElement('span');
    timeEl.className = 'log-time';
    timeEl.textContent = formatTime(log.timestamp);
    header.append(levelEl, timeEl);

    const message = document.createElement('div');
    message.className = 'log-message';
    message.textContent = String(log.message || '');
    entry.append(header, message);

    if (log.details !== null && log.details !== undefined) {
      const details = document.createElement('div');
      details.className = 'log-details';
      details.textContent = JSON.stringify(log.details, null, 2);
      entry.appendChild(details);
    }
    fragment.appendChild(entry);
  }
  container.appendChild(fragment);
}

async function loadLogs() {
  if (loading || document.hidden) return;
  loading = true;
  try {
    const response = await sendMessage({ action: 'getLogs' });
    renderLogs(response?.logs || []);
  } catch (error) {
    document.getElementById('logsContainer').innerHTML = `<div class="empty-state">读取失败：${error.message}</div>`;
  } finally {
    loading = false;
  }
}

async function clearLogs() {
  if (!confirm('确定要清空日志吗？')) return;
  try {
    await sendMessage({ action: 'clearLogs' });
    await loadLogs();
  } catch (error) {
    alert('清空失败: ' + error.message);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadLogs();
  document.getElementById('refreshBtn').addEventListener('click', loadLogs);
  document.getElementById('clearBtn').addEventListener('click', clearLogs);
  document.getElementById('backBtn').addEventListener('click', () => {
    window.location.href = 'popup.html';
  });
  setInterval(loadLogs, 3000);
});