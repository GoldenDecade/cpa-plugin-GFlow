// popup.js - GFlow 登录助手配置界面交互
function field(id) { return document.getElementById(id); }

function showStatus(text, type = 'info') {
  const el = field('status');
  el.textContent = text;
  el.className = 'status-banner ' + type;
}

function busy(val) {
  field('saveAndSyncBtn').disabled = val;
  field('saveOnlyBtn').disabled = val;
  field('quickFillBtn').disabled = val;
}

async function sendMsg(action, config) {
  const resp = await chrome.runtime.sendMessage({ action, config });
  if (!resp?.ok && !resp?.success) {
    throw new Error(resp?.message || resp?.error || '无法与 GFlow 扩展后台建立通信');
  }
  return resp.result || resp;
}

function parseAndFillConfig(rawText) {
  const text = String(rawText || '').trim();
  if (!text) return false;
  try {
    const data = JSON.parse(text);
    if (data.apiUrl) field('apiUrl').value = data.apiUrl;
    if (data.connectionToken) field('connectionToken').value = data.connectionToken;
    if (data.loginAccount) field('email').value = data.loginAccount;
    return true;
  } catch (_) {
    return false;
  }
}

function renderState(state) {
  const isPaired = Boolean(state.configured);
  if (state.apiUrl) field('apiUrl').value = state.apiUrl;
  if (state.loginAccount) field('email').value = state.loginAccount;
  if (state.autoSync !== undefined) field('autoSync').checked = Boolean(state.autoSync);
  
  if (state.lastSync) {
    const d = new Date(state.lastSync.timestamp);
    const timeStr = Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString();
    showStatus(`${state.lastSync.success ? '✅ 同步成功' : '❌ 同步失败'} (${timeStr})\n${state.lastSync.message || ''}`, state.lastSync.success ? 'success' : 'error');
  } else if (isPaired) {
    showStatus('已配置本机连接，登录 Flow 后点击“保存并立即同步”。', 'info');
  } else {
    showStatus('请从 GFlow 页面点击“复制扩展配置”，粘贴到此处即可。', 'info');
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  try {
    const state = await sendMsg('state');
    renderState(state);
  } catch (err) {
    showStatus(err.message, 'error');
  }

  // 快捷识别
  field('quickFillBtn').addEventListener('click', () => {
    const val = field('quickPaste').value.trim();
    if (!val) return showStatus('请先粘贴配置文本', 'error');
    if (parseAndFillConfig(val)) {
      field('quickPaste').value = '';
      showStatus('配置已自动填入，请核对邮箱后点击“保存并立即同步”。', 'success');
    } else {
      showStatus('未能解析配置 JSON，请确认是从 GFlow 页面点击【复制扩展配置】所得。', 'error');
    }
  });

  // 快捷框直接输入自动填入
  field('quickPaste').addEventListener('input', () => {
    const val = field('quickPaste').value.trim();
    if (val.startsWith('{') && val.endsWith('}')) {
      if (parseAndFillConfig(val)) {
        field('quickPaste').value = '';
        showStatus('已自动识别并填充配置！', 'success');
      }
    }
  });

  // 提交并同步
  field('setup').addEventListener('submit', async (e) => {
    e.preventDefault();
    busy(true);
    showStatus('正在连接 GFlow 后台并同步登录态...', 'info');
    try {
      const apiUrl = field('apiUrl').value.trim();
      const connectionToken = field('connectionToken').value.trim();
      const loginAccount = validateEmail(field('email').value);
      const autoSync = field('autoSync').checked;

      const connection = validateConnection({ product: 'GFlow', apiUrl, connectionToken });
      await chrome.permissions.request({ origins: [connectionPermission(connection.apiUrl)] });
      await sendMsg('save', { connection, loginAccount, autoSync });

      const syncResult = await sendMsg('sync');
      showStatus(`✅ 同步成功！${syncResult.message || ''}`, 'success');
    } catch (err) {
      showStatus(err.message, 'error');
    } finally {
      busy(false);
    }
  });

  // 仅保存
  field('saveOnlyBtn').addEventListener('click', async () => {
    busy(true);
    try {
      const apiUrl = field('apiUrl').value.trim();
      const connectionToken = field('connectionToken').value.trim();
      const loginAccount = validateEmail(field('email').value);
      const autoSync = field('autoSync').checked;

      const connection = validateConnection({ product: 'GFlow', apiUrl, connectionToken });
      await chrome.permissions.request({ origins: [connectionPermission(connection.apiUrl)] });
      await sendMsg('save', { connection, loginAccount, autoSync });
      showStatus('配置已保存成功。', 'success');
    } catch (err) {
      showStatus(err.message, 'error');
    } finally {
      busy(false);
    }
  });

  // 日志页面
  field('logsBtn').addEventListener('click', () => {
    window.location.href = 'logs.html';
  });

  // 清除配置
  field('forgetBtn').addEventListener('click', async () => {
    if (!confirm('确定要清除本机的 GFlow 扩展连接配置吗？')) return;
    try {
      const state = await sendMsg('forget');
      renderState(state);
      field('connectionToken').value = '';
      showStatus('配置已清除。', 'info');
    } catch (err) {
      showStatus(err.message, 'error');
    }
  });
});