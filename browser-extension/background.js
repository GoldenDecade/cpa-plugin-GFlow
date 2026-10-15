// background.js - GFlow 登录助手后台服务
importScripts('common.js');

const ALARM = 'gflow-cookie-sync';
const FLOW_URL = 'https://flow.google.com/projects';
let activeSync = null;

// 日志系统
const Logger = {
  async log(level, message, details = null) {
    const timestamp = new Date().toISOString();
    const safeDetails = sanitizeLogDetails(details);
    const logEntry = { timestamp, level, message, details: safeDetails };
    console.log(`[${level}] ${message}`, safeDetails || '');
    try {
      const { logs = [] } = await chrome.storage.local.get(['logs']);
      const updatedLogs = [logEntry, ...logs].slice(0, 100);
      await chrome.storage.local.set({ logs: updatedLogs });
    } catch (_) {}
  },
  info(msg, d) { return this.log('INFO', msg, d); },
  error(msg, d) { return this.log('ERROR', msg, d); },
  success(msg, d) { return this.log('SUCCESS', msg, d); },
  async getLogs() {
    const { logs = [] } = await chrome.storage.local.get(['logs']);
    return logs;
  },
  async clearLogs() {
    await chrome.storage.local.set({ logs: [] });
  }
};

function sanitizeLogDetails(value, key = '') {
  if (value == null) return value;
  if (/^(authorization|connectionToken|google_cookies|session_token|password|secret)$/i.test(key)) {
    return '[REDACTED]';
  }
  if (Array.isArray(value)) return value.map(item => sanitizeLogDetails(item));
  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, sanitizeLogDetails(v, k)])
    );
  }
  if (typeof value === 'string') {
    return value
      .replace(/Bearer\s+[^\s]+/gi, 'Bearer [REDACTED]')
      .replace(/((?:^|[;\s])(?:__Secure-)?(?:OSID|SID|HSID|SSID|APISID|SAPISID)=)[^;\s]+/gi, '$1[REDACTED]');
  }
  return value;
}

async function publicState() {
  const state = await chrome.storage.local.get(['config', 'lastSync']);
  const config = state.config || {};
  return {
    configured: Boolean(config.connectionToken),
    loginAccount: config.loginAccount || '',
    apiUrl: config.apiUrl || '',
    autoSync: config.autoSync !== false,
    lastSync: state.lastSync || null
  };
}

async function restoreAlarm() {
  const { config } = await chrome.storage.local.get('config');
  await chrome.alarms.clear(ALARM);
  if (config?.connectionToken && config.autoSync) {
    await chrome.alarms.create(ALARM, { periodInMinutes: 60 });
  }
}

async function saveConfiguration(input) {
  const state = await chrome.storage.local.get('config');
  const connection = validateConnection(input.connection || state.config);
  const config = {
    ...connection,
    loginAccount: validateEmail(input.loginAccount),
    autoSync: Boolean(input.autoSync)
  };
  if (!await chrome.permissions.contains({ origins: [connectionPermission(config.apiUrl)] })) {
    throw new Error('请授权扩展连接本机 GFlow');
  }
  await chrome.storage.local.set({ config });
  await restoreAlarm();
  await Logger.info('GFlow 连接配置已保存', { apiUrl: config.apiUrl, loginAccount: config.loginAccount });
  return publicState();
}

async function waitForTabReady(tabId, maxWaitMs = 15000) {
  const startTime = Date.now();
  while (Date.now() - startTime < maxWaitMs) {
    try {
      const tab = await chrome.tabs.get(tabId);
      if (tab && tab.status === 'complete') return tab;
    } catch (_) {
      break;
    }
    await new Promise(r => setTimeout(r, 500));
  }
}

async function closeTemporaryTab(tab) {
  if (tab && typeof tab.id === 'number') {
    try { await chrome.tabs.remove(tab.id); } catch (_) {}
  }
}

async function executeSync() {
  const { config } = await chrome.storage.local.get('config');
  if (!config) throw new Error('请先从 GFlow 复制配置并保存');
  const connection = validateConnection(config);
  const loginAccount = validateEmail(config.loginAccount);

  await Logger.info('开始同步 GFlow 登录凭据...', { account: loginAccount });

  // 1. 若支持 chrome.tabs.create，打开不可见后台标签页激活 Flow 会话
  let tempTab = null;
  if (chrome.tabs?.create && chrome.tabs?.get) {
    try {
      await Logger.info('在后台打开 Google Flow 页面以激活登录态...');
      tempTab = await chrome.tabs.create({ url: FLOW_URL, active: false });
      await waitForTabReady(tempTab.id);
      // 等待 5 秒供 Angular SPA 完成会话初始化
      await new Promise(r => setTimeout(r, 5000));
      const loadedTab = await chrome.tabs.get(tempTab.id).catch(() => null);
      let loadedHost = '';
      try { loadedHost = new URL(loadedTab?.url || '').hostname.toLowerCase(); } catch (_) {}
      if (loadedHost && loadedHost !== 'flow.google.com') {
        await closeTemporaryTab(tempTab);
        tempTab = null;
        throw new Error('Google Flow 未保持登录状态。请在当前浏览器登录 Google 并打开 flow.google.com 确认可正常访问后重试。');
      }
    } catch (tabErr) {
      if (tabErr.message.includes('未保持登录状态')) throw tabErr;
      await Logger.info('后台标签预热跳过，直接提取 Cookie', { error: tabErr.message });
    }
  }

  // 2. 提取 Cookie
  const cookieQuery = { url: FLOW_URL };
  if (chrome.tabs?.query && chrome.cookies?.getAllCookieStores) {
    try {
      const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      const stores = await chrome.cookies.getAllCookieStores();
      const store = stores.find(item => item.tabIds.includes(tabs[0]?.id));
      if (store) cookieQuery.storeId = store.id;
    } catch (_) {}
  }
  const rawCookies = await chrome.cookies.getAll(cookieQuery);
  if (tempTab) {
    await closeTemporaryTab(tempTab);
    tempTab = null;
  }

  const googleCookies = serializeFlowCookies(rawCookies);
  await Logger.info('Cookie 提取成功，正在提交至本机 GFlow 内核...');

  const payload = {
    login_account: loginAccount,
    google_cookies: googleCookies,
    protocol_mode: 'protocol',
    user_agent: typeof navigator !== 'undefined' ? navigator.userAgent : ''
  };

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  let response;
  try {
    response = await fetch(connection.apiUrl, {
      method: 'POST',
      redirect: 'error',
      cache: 'no-store',
      credentials: 'omit',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + connection.connectionToken
      },
      body: JSON.stringify(payload),
      signal: controller.signal
    });
  } catch (error) {
    const errText = error.name === 'AbortError' ? 'GFlow 同步超时，请检查代理设置后重试' : '无法连接本机 GFlow，请确认 EasyCPA 内核运行中';
    await Logger.error(errText);
    throw new Error(errText);
  } finally {
    clearTimeout(timer);
  }

  let result = null;
  try { result = await response.json(); } catch (_) {}
  if (!response.ok || !result?.success) {
    if (response.status === 401 || response.status === 403) {
      await Logger.error('连接凭据失效');
      throw new Error('连接凭据失效，请回到 GFlow 重新复制扩展配置');
    }
    if (response.status === 404) {
      await Logger.error('接口未找到');
      throw new Error('当前 GFlow 版本不支持扩展同步，请更新插件');
    }
    const detail = result?.error;
    const safeMessage = typeof detail?.message === 'string'
      && detail.message.length <= 500
      && !/(cookie\s*[:=]|connectionToken|access_token)/i.test(detail.message)
      ? detail.message : null;
    const code = /^gflow_[a-z_]+$/.test(detail?.code || '') ? detail.code : null;
    const errorMsg = safeMessage
      ? safeMessage + (code ? ' [' + code + ']' : '')
      : 'GFlow 同步失败（HTTP ' + response.status + '）。请查看日志获取详细诊断。';
    await Logger.error('同步失败', { error: errorMsg });
    throw new Error(errorMsg);
  }

  const actionMsg = result.action === 'updated' ? 'GFlow 账号登录态已更新' : 'GFlow 账号已添加';
  await Logger.success(`✅ ${actionMsg}`, { action: result.action });
  return { success: true, action: result.action, message: actionMsg };
}

function syncNow() {
  if (activeSync) return activeSync;
  activeSync = (async () => {
    let result;
    try {
      result = await executeSync();
    } catch (error) {
      result = { success: false, message: error.message };
    }
    await chrome.storage.local.set({
      lastSync: { success: result.success, message: result.message, timestamp: Date.now() }
    });
    if (chrome.action?.setBadgeText) {
      await chrome.action.setBadgeText({ text: result.success ? 'OK' : '!' });
      await chrome.action.setBadgeBackgroundColor({ color: result.success ? '#0d9488' : '#dc2626' });
    }
    return result;
  })().finally(() => { activeSync = null; });
  return activeSync;
}

chrome.runtime.onMessage.addListener((request, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return false;
  const action = request.action;
  if (action === 'state' || action === 'getConfig') {
    publicState().then(result => respond({ ok: true, success: true, result, config: result }), () => respond({ ok: false, success: false }));
    return true;
  }
  if (action === 'save' || action === 'saveConfig') {
    saveConfiguration(request.config).then(result => respond({ ok: true, success: true, result, config: result }), e => respond({ ok: false, success: false, message: e.message, error: e.message }));
    return true;
  }
  if (action === 'sync' || action === 'testNow') {
    syncNow().then(result => respond({ ok: true, success: result.success, result, ...result }), e => respond({ ok: false, success: false, message: e.message, error: e.message }));
    return true;
  }
  if (action === 'forget') {
    chrome.storage.local.remove(['config', 'lastSync'])
      .then(restoreAlarm)
      .then(publicState)
      .then(result => respond({ ok: true, result }), () => respond({ ok: false }));
    return true;
  }
  if (action === 'getLogs') {
    Logger.getLogs().then(logs => respond({ ok: true, success: true, logs }), () => respond({ ok: false, logs: [] }));
    return true;
  }
  if (action === 'clearLogs') {
    Logger.clearLogs().then(() => respond({ ok: true, success: true }), () => respond({ ok: false }));
    return true;
  }
  return false;
});

if (chrome.alarms?.onAlarm) {
  chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) void syncNow(); });
}
if (chrome.runtime?.onStartup) {
  chrome.runtime.onStartup.addListener(() => { void restoreAlarm(); });
}
if (chrome.runtime?.onInstalled) {
  chrome.runtime.onInstalled.addListener(() => { void restoreAlarm(); });
}