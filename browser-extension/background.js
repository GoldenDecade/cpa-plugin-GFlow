importScripts('common.js');
const ALARM = 'gflow-cookie-sync';
let activeSync = null;

async function publicState() {
  const state = await chrome.storage.local.get(['config', 'lastSync']);
  const config = state.config || {};
  return { configured: Boolean(config.connectionToken), loginAccount: config.loginAccount || '', autoSync: config.autoSync !== false, lastSync: state.lastSync || null };
}

async function restoreAlarm() {
  const { config } = await chrome.storage.local.get('config');
  await chrome.alarms.clear(ALARM);
  if (config?.connectionToken && config.autoSync) await chrome.alarms.create(ALARM, { periodInMinutes: 60 });
}

async function saveConfiguration(input) {
  const state = await chrome.storage.local.get('config');
  const connection = validateConnection(input.connection || state.config);
  const config = { ...connection, loginAccount: validateEmail(input.loginAccount), autoSync: Boolean(input.autoSync) };
  if (!await chrome.permissions.contains({ origins: [connectionPermission(config.apiUrl)] })) throw new Error('请授权扩展连接本机 GFlow');
  await chrome.storage.local.set({ config });
  await restoreAlarm();
  return publicState();
}

async function executeSync() {
  const { config } = await chrome.storage.local.get('config');
  if (!config) throw new Error('请先从 GFlow 复制配置并保存');
  const connection = validateConnection(config);
  const loginAccount = validateEmail(config.loginAccount);
  // 无痕窗口或不同 Cookie 存储区应读取当前窗口的登录态。
  const cookieQuery = { url: 'https://flow.google.com/projects' };
  if (chrome.tabs?.query && chrome.cookies.getAllCookieStores) {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const stores = await chrome.cookies.getAllCookieStores();
    const store = stores.find(item => item.tabIds.includes(tabs[0]?.id));
    if (store) cookieQuery.storeId = store.id;
  }
  const cookies = await chrome.cookies.getAll(cookieQuery);
  const payload = { login_account: loginAccount, google_cookies: serializeFlowCookies(cookies), protocol_mode: 'protocol' };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120000);
  let response;
  try {
    response = await fetch(connection.apiUrl, { method: 'POST', redirect: 'error', cache: 'no-store', credentials: 'omit',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + connection.connectionToken },
      body: JSON.stringify(payload), signal: controller.signal });
  } catch (error) {
    throw new Error(error.name === 'AbortError' ? 'GFlow 同步超时，请稍后重试' : '无法连接本机 GFlow，请确认 EasyCPA 内核运行中');
  } finally { clearTimeout(timer); }
  // 成功与失败都读取 JSON；旧版后端只返回 HTTP 500 时也可显示其安全提示。
  let result = null;
  try { result = await response.json(); } catch (_) {}
  if (!response.ok || !result?.success) {
    if (response.status === 401 || response.status === 403) throw new Error('连接凭据失效，请回到 GFlow 重新复制扩展配置');
    if (response.status === 404) throw new Error('当前 GFlow 版本不支持扩展同步，请更新插件');
    const detail = result?.error;
    const safeMessage = typeof detail?.message === 'string'
      && detail.message.length <= 500
      && !/(cookie\s*[:=]|bearer\s|connectionToken|access_token|https?:\/\/|[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})/i.test(detail.message)
      ? detail.message : null;
    const code = /^gflow_[a-z_]+$/.test(detail?.code || '') ? detail.code : null;
    if (safeMessage) throw new Error(safeMessage + (code ? ' [' + code + ']' : ''));
    throw new Error('GFlow 同步失败（HTTP ' + response.status + '）。请更新插件后重试以查看具体原因。');
  }
  return { success: true, action: result.action, message: result.action === 'updated' ? 'GFlow 账号登录态已更新' : 'GFlow 账号已添加' };
}

function syncNow() {
  if (activeSync) return activeSync;
  activeSync = (async () => {
    let result;
    try { result = await executeSync(); }
    catch (error) { result = { success: false, message: error.message }; }
    await chrome.storage.local.set({ lastSync: { success: result.success, message: result.message, timestamp: Date.now() } });
    await chrome.action.setBadgeText({ text: result.success ? 'OK' : '!' });
    await chrome.action.setBadgeBackgroundColor({ color: result.success ? '#0d9488' : '#dc2626' });
    return result;
  })().finally(() => { activeSync = null; });
  return activeSync;
}

chrome.runtime.onMessage.addListener((request, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return false;
  const operation = request.action === 'state' ? publicState
    : request.action === 'save' ? () => saveConfiguration(request.config)
    : request.action === 'sync' ? syncNow
    : request.action === 'forget' ? async () => { await chrome.storage.local.remove(['config', 'lastSync']); await restoreAlarm(); return publicState(); }
    : null;
  if (!operation) return false;
  Promise.resolve().then(operation).then(result => respond({ ok: true, result }), () => respond({ ok: false, message: '操作失败，请检查配置后重试' }));
  return true;
});
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) void syncNow(); });
chrome.runtime.onStartup.addListener(() => { void restoreAlarm(); });
chrome.runtime.onInstalled.addListener(() => { void restoreAlarm(); });
