const field = id => document.getElementById(id);
let paired = false;
function show(message) { field('status').textContent = message; }
function busy(value) { for (const id of ['save', 'sync', 'forget']) field(id).disabled = value; }
async function message(action, config) {
  const response = await chrome.runtime.sendMessage({ action, config });
  if (!response?.ok) throw new Error(response?.message || '无法连接 GFlow 扩展后台');
  return response.result;
}
function render(state) {
  paired = state.configured;
  field('paired').textContent = paired ? '已保存本机连接配置；不更换连接时可留空。' : '首次粘贴一次即可；配置含管理凭据，请勿分享。';
  field('email').value = state.loginAccount;
  field('auto').checked = state.autoSync;
  show(state.lastSync ? new Date(state.lastSync.timestamp).toLocaleString() + '\n' + state.lastSync.message : paired ? '已配置，登录 Flow 后点击“立即同步”。' : '请从 GFlow 添加账号窗口复制扩展配置。');
}
document.addEventListener('DOMContentLoaded', async () => {
  try { render(await message('state')); } catch (error) { show(error.message); }
  field('setup').addEventListener('submit', async event => {
    event.preventDefault(); busy(true);
    try {
      const text = field('connection').value.trim();
      let connection;
      if (text) {
        try { connection = validateConnection(JSON.parse(text)); } catch (_) { throw new Error('扩展配置无效，请回到 GFlow 重新复制'); }
        if (!await chrome.permissions.request({ origins: [connectionPermission(connection.apiUrl)] })) throw new Error('需要授权连接本机 GFlow');
      } else if (!paired) { throw new Error('请先粘贴 GFlow 扩展配置'); }
      await message('save', { connection, loginAccount: validateEmail(field('email').value), autoSync: field('auto').checked });
      paired = true;
      field('connection').value = '';
      field('paired').textContent = '已保存本机连接配置，无需再次粘贴。';
      show('正在同步登录态…');
      const result = await message('sync'); show(result.message);
    } catch (error) { show(error.message); } finally { busy(false); }
  });
  field('sync').addEventListener('click', async () => {
    busy(true); show('正在同步登录态…');
    try { show((await message('sync')).message); } catch (error) { show(error.message); } finally { busy(false); }
  });
  field('forget').addEventListener('click', async () => {
    try { render(await message('forget')); field('connection').value = ''; } catch (error) { show(error.message); }
  });
});
