"""管理连接回归：使用模拟接口验证页面状态，不导入账号、不访问 Google。"""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

PAGE = Path(__file__).resolve().parents[1] / "static" / "manage.html"

HARNESS = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const elements = new Map();
function element() {
  return { value: '', textContent: '', innerHTML: '', disabled: false, checked: false,
    style: {}, children: [], append(...nodes) { this.children.push(...nodes); },
    replaceChildren(...nodes) { this.children = nodes; }, focus() {} };
}
const events = new Map(), requests = [];
let mode = 'ok', hasSession = false, copiedConfig = '';
const location = { origin: 'http://127.0.0.1:8317', hash: '#gflow_session=test-ticket', pathname: '/v0/resource/plugins/gflow/manage', search: '' };
const context = vm.createContext({
  document: {
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement: element
  },
  window: { location, history: { replaceState() { location.hash = ''; } },
    addEventListener(name, fn) { events.set(name, fn); } },
  navigator: { clipboard: { async writeText(value) { copiedConfig = value; } } },
  console, AbortController, URLSearchParams, setTimeout, clearTimeout,
  fetch: async (path, opts) => {
    requests.push({ path, opts });
    if (path.endsWith('/bootstrap')) {
      assert.equal(opts.headers.Authorization, undefined);
      assert.equal(opts.credentials, 'same-origin');
      const allowed = opts.headers['X-GFlow-Session'] === 'test-ticket' || hasSession;
      if (!allowed || mode === 'missing-setup') return {
        status: 401, ok: false, json: async () => ({error:{message:'请从 EasyCPA 插件菜单重新打开 GFlow'}})
      };
      hasSession = true;
      return { status: 200, ok: true, json: async () => ({management_key:'test-management-secret'}) };
    }
    assert.equal(opts.headers.Authorization, 'Bearer test-management-secret');
    let status = mode === 'wrong' ? 401 : 200;
    if (mode === 'config-failure' && path.endsWith('/config')) status = 500;
    const data = path.endsWith('/status')
      ? { total_tokens: 0, active_tokens: 0, total_credits: 0, version: '3.13.9', python: 'D:/test/python.exe' }
      : path.endsWith('/tokens') ? { tokens: [], total: 0 }
      : path.endsWith('/models') ? { models: [] }
      : status === 500 ? { error: { message: 'config temporarily unavailable' } } : {};
    return { status, ok: status === 200, json: async () => data };
  }
});
Object.defineProperty(context, 'localStorage', { get() { throw new Error('Must not access storage'); } });
vm.runInContext(SCRIPT, context);
const el = id => context.document.getElementById(id);
(async () => {
  await events.get('DOMContentLoaded')();
  assert.equal(el('stat-python-ver').textContent, 'Python 3.13.9');
  assert.equal(el('stat-total-tokens').textContent, 0);
  assert.equal(el('save-settings-button').disabled, false);
  assert.equal(location.hash, '');
  assert.ok(requests.some(r => r.path.endsWith('/models')));
  await context.copyExtensionConfig();
  const pairing = JSON.parse(copiedConfig);
  assert.equal(pairing.product, 'GFlow');
  assert.equal(pairing.connectionToken, 'test-management-secret');
  assert.equal(pairing.apiUrl, 'http://127.0.0.1:8317/v0/management/plugins/gflow/api/extension-sync');
  assert.ok(requests.every(r => !r.path.includes('test-management-secret') && !r.path.includes('test-ticket')));
  console.log('PASS startup automatically connects without a key input or secret in URL');
  await context.initializeManagement();
  assert.equal(el('stat-python-ver').textContent, 'Python 3.13.9');
  console.log('PASS page refresh uses the authenticated browser session');
  mode = 'wrong';
  await context.loadAll();
  assert.match(el('connection-status').textContent, /401/);
  assert.equal(el('save-settings-button').disabled, true);
  assert.ok(!el('stat-python-ver').textContent.includes('离线'));
  console.log('PASS invalid configured key is not misreported as Python offline');
  mode = 'ok';
  await context.initializeManagement();
  assert.equal(el('stat-python-ver').textContent, 'Python 3.13.9');
  console.log('PASS automatic retry recovers from configuration correction');
  mode = 'config-failure';
  await context.loadAll();
  assert.equal(el('save-settings-button').disabled, true);
  let count = requests.length;
  await context.saveSettings();
  assert.equal(requests.length, count);
  console.log('PASS failed config load blocks saving defaults');
  mode = 'missing-setup'; hasSession = false;
  count = requests.length;
  await context.initializeManagement();
  assert.equal(requests.length, count + 1);
  assert.equal(el('add-token-button').disabled, true);
  assert.match(el('connection-status').textContent, /插件菜单/);
  console.log('PASS missing bootstrap session does not call privileged management APIs');
  events.get('pagehide')();
  count = requests.length;
  await assert.rejects(context.apiRequest('/v0/management/plugins/gflow/api/status'));
  assert.equal(requests.length, count);
  console.log('PASS closing page clears in-memory management credentials');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""

class ManagementUITest(unittest.TestCase):
    def test_management_connection(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行页面逻辑回归")
        html = PAGE.read_text(encoding="utf-8")
        self.assertNotIn('id="mgmtKey"', html)
        self.assertNotIn('id="connection-form"', html)
        self.assertIn("如何获取 Cookie / Session Token", html)
        self.assertIn("https://github.com/daodeqing/cpa-plugin-GFlow/tree/main/browser-extension", html)
        self.assertNotIn("Flow2API", html)
        script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        result = subprocess.run(
            [node, "-"], input="const SCRIPT = " + json.dumps(script) + chr(59) + chr(10) + HARNESS,
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count("PASS "), 7, result.stdout)
        print(result.stdout, end="")

if __name__ == "__main__":
    unittest.main()
