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
const events = new Map();
const requests = [];
let mode = 'ok';
const context = vm.createContext({
  document: {
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement: element
  },
  window: { addEventListener(name, fn) { events.set(name, fn); } },
  console, AbortController, setTimeout, clearTimeout,
  fetch: async (path, opts) => {
    requests.push({ path, opts });
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
const connect = async () => {
  el('mgmtKey').value = 'test-management-secret';
  await context.connectManagement({ preventDefault() {} });
};
(async () => {
  events.get('DOMContentLoaded')();
  assert.equal(requests.length, 0);
  assert.equal(el('stat-python-ver').textContent, '未检测（未连接）');
  assert.equal(el('save-settings-button').disabled, true);
  console.log('PASS initial page sends no unauthenticated requests');
  await connect();
  assert.equal(el('stat-python-ver').textContent, 'Python 3.13.9');
  assert.equal(el('stat-total-tokens').textContent, 0);
  assert.equal(el('mgmtKey').value, '');
  assert.equal(el('save-settings-button').disabled, false);
  assert.ok(requests.some(r => r.path.endsWith('/models')));
  assert.ok(requests.every(r => r.path.startsWith('/v0/management/plugins/gflow/')));
  assert.ok(!requests.some(r => /test-management-secret/.test(r.path)));
  console.log('PASS valid management key loads empty accounts, config and real model route');
  context.disconnectManagement();
  assert.equal(el('save-settings-button').disabled, true);
  assert.equal(el('add-token-button').disabled, true);
  let count = requests.length;
  await assert.rejects(context.apiRequest('/v0/management/plugins/gflow/api/status'));
  assert.equal(requests.length, count);
  console.log('PASS disconnect clears credentials and disables mutations');
  mode = 'wrong';
  await connect();
  assert.match(el('connection-status').textContent, /401/);
  assert.match(el('stat-python-ver').textContent, /未连接/);
  assert.ok(!el('stat-python-ver').textContent.includes('离线'));
  console.log('PASS HTTP 401 is authentication failure, not Python offline');
  mode = 'ok';
  await connect();
  assert.equal(el('stat-python-ver').textContent, 'Python 3.13.9');
  console.log('PASS reconnect recovers from wrong key');
  mode = 'config-failure';
  await context.loadAll();
  assert.equal(el('save-settings-button').disabled, true);
  count = requests.length;
  await context.saveSettings();
  assert.equal(requests.length, count);
  console.log('PASS failed config load blocks saving defaults');
  events.get('pagehide')();
  assert.equal(el('mgmtKey').value, '');
  assert.equal(el('refresh-button').disabled, true);
  console.log('PASS closing page clears connection state');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""

class ManagementUITest(unittest.TestCase):
    def test_management_connection(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "需要 Node.js 执行页面逻辑回归")
        html = PAGE.read_text(encoding="utf-8")
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
