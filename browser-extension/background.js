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
  const cookies = await chrome.cookies.getAll({ url: 'https://flow.google.com/projects' });
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
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) throw new Error('连接凭据失效，请回到 GFlow 重新复制扩展配置');
    if (response.status === 404) throw new Error('当前 GFlow 版本不支持扩展同步，请更新插件');
    throw new Error('GFlow 未接受同步（HTTP ' + response.status + '），请检查网络、登录账号和 Cookie 后重试');
  }
  const result = await response.json();
  if (!result.success) throw new Error('GFlow 未完成同步，请检查账号状态后重试');
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
