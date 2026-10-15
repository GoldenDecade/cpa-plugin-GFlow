const GFLOW_SYNC_PATH = '/v0/management/plugins/gflow/api/extension-sync';

function validateConnection(value) {
  if (!value || value.product !== 'GFlow') throw new Error('请粘贴从 GFlow 添加账号窗口复制的配置');
  let url;
  try { url = new URL(value.apiUrl); } catch (_) { throw new Error('GFlow 连接地址无效'); }
  if (!['127.0.0.1', 'localhost'].includes(url.hostname) || !['http:', 'https:'].includes(url.protocol)
      || url.username || url.password || url.search || url.hash || url.pathname !== GFLOW_SYNC_PATH) {
    throw new Error('扩展仅连接本机 GFlow；请重新复制配置');
  }
  const connectionToken = String(value.connectionToken || '').trim();
  if (!connectionToken || connectionToken.length > 512 || /[\x00-\x1f\x7f]/.test(connectionToken)) {
    throw new Error('连接凭据无效，请重新复制 GFlow 扩展配置');
  }
  return { product: 'GFlow', apiUrl: url.href, connectionToken };
}

function validateEmail(value) {
  const email = String(value || '').trim().toLowerCase();
  if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw new Error('请填写当前 Google 账号邮箱');
  return email;
}

function connectionPermission(apiUrl) {
  const url = new URL(apiUrl);
  return url.protocol + '//' + url.hostname + '/*';
}

function serializeFlowCookies(cookies) {
  const scope = new URL('https://flow.google.com/projects');
  const selected = cookies.filter(cookie => {
    const domain = String(cookie.domain || '').replace(/^\./, '').toLowerCase();
    const hostMatches = cookie.hostOnly ? scope.hostname === domain : scope.hostname === domain || scope.hostname.endsWith('.' + domain);
    const path = cookie.path || '/';
    const pathMatches = scope.pathname === path || scope.pathname.startsWith(path.endsWith('/') ? path : path + '/');
    return cookie.name && cookie.value && hostMatches && pathMatches;
  });
  const names = new Set(selected.map(cookie => cookie.name));
  if (!['OSID', '__Secure-OSID'].some(name => names.has(name))
      || !['SID', 'HSID', 'SSID', 'APISID', 'SAPISID', '__Secure-1PSID', '__Secure-3PSID'].some(name => names.has(name))) {
    throw new Error('未找到完整 Flow 登录态，请先在本浏览器登录 flow.google.com，再重试');
  }
  return JSON.stringify(selected.map(cookie => ({
    name: cookie.name, value: cookie.value, domain: cookie.domain, path: cookie.path || '/',
    secure: Boolean(cookie.secure), httpOnly: Boolean(cookie.httpOnly), hostOnly: Boolean(cookie.hostOnly),
    ...(cookie.sameSite ? { sameSite: cookie.sameSite } : {}),
    ...(cookie.expirationDate ? { expirationDate: cookie.expirationDate } : {}),
    ...(cookie.partitionKey ? { partitionKey: cookie.partitionKey } : {})
  })));
}
