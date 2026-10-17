"""只使用虚构认证字段；不读取真实浏览器 Cookie。"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "python/flow2api"))
from src.services.flow_client import FlowClient

class BrowserContextTest(unittest.IsolatedAsyncioTestCase):
    async def test_credit_rpc_loads_upstream_bootstrap_instead_of_plugin_page_context(self):
        client=FlowClient(None)
        client._set_request_fingerprint({"gflow_frontend":{
            "bl":"boq_labs-ai-sandbox-frontend_ignored","sid":"111",
            "at":"ignored-token", "source_path":"/projects"}})
        bootstrap=json.dumps({
            "bl":"boq_labs-ai-sandbox-frontend_upstream",
            "FdrFJe":"222", "SNlM0e":"fake-xsrf:upstream",
        })
        client._load_flow_frontend_bootstrap=AsyncMock(return_value=bootstrap)
        client._make_text_request=AsyncMock(return_value=json.dumps([["wrb.fr","nzlxg",json.dumps([12])]]))
        result=await client.get_credits(google_cookies="SID=fake; OSID=synthetic")
        self.assertEqual(result['credits'],12)
        client._load_flow_frontend_bootstrap.assert_awaited_once()
        request=client._make_text_request.call_args.kwargs
        self.assertEqual(parse_qs(request["raw_body"])["at"],["fake-xsrf:upstream"])
        self.assertEqual(parse_qs(urlparse(request["url"]).query)["f.sid"],["222"])
        self.assertEqual(request["headers"]["Cookie"],"SID=fake; OSID=synthetic")

    async def test_content_script_binds_account_and_does_not_return_credentials_on_mismatch(self):
        script=(ROOT / "browser-extension/flow-session.js").read_text(encoding="utf-8")
        harness=r"""
const vm=require('node:vm'),assert=require('node:assert/strict');let listener;
const source='window.WIZ_global_data='+JSON.stringify({oPEP7c:'example@example.test',SNlM0e:'fake-xsrf:token',FdrFJe:'123456',bl:'boq_labs-ai-sandbox-frontend_20261014.00_p0'});
const context=vm.createContext({chrome:{runtime:{id:'gflow-test',onMessage:{addListener(fn){listener=fn;}}}},document:{scripts:[{textContent:source}]},location:{pathname:'/projects'}});
vm.runInContext(SCRIPT,context);let result;
listener({action:'gflow-page-session',email:'Example@example.test'},{id:'gflow-test'},value=>{result=value;});
assert.equal(result.signed_in,true);assert.equal(result.account_matches,true);assert.equal(result.frontend.at,'fake-xsrf:token');
listener({action:'gflow-page-session',email:'other@example.test'},{id:'gflow-test'},value=>{result=value;});
assert.equal(result.account_matches,false);assert.equal(result.frontend,undefined);
assert.equal(listener({action:'gflow-page-session',email:'example@example.test'},{id:'other-extension'},()=>{throw new Error('unexpected');}),false);
"""
        result=subprocess.run([shutil.which("node"),"-"],input="const SCRIPT="+json.dumps(script)+";\n"+harness,text=True,capture_output=True,encoding="utf-8",timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    async def test_browser_credit_probe_is_read_only_and_never_returns_credentials(self):
        script=(ROOT / "browser-extension/flow-session.js").read_text(encoding="utf-8")
        harness=r"""
const vm=require('node:vm'),assert=require('node:assert/strict');let listener,mode='ok',calls=0;
const source=JSON.stringify({oPEP7c:'example@example.test',SNlM0e:'fake-xsrf:token',FdrFJe:'123456',bl:'boq_labs-ai-sandbox-frontend_test'});
const context=vm.createContext({URL,URLSearchParams,AbortController,setTimeout,clearTimeout,
  chrome:{runtime:{id:'gflow-test',onMessage:{addListener(fn){listener=fn;}}}},document:{scripts:[{textContent:source}]},location:{pathname:'/projects'},
  fetch:async(url,opts)=>{calls++;const parsed=new URL(url);assert.equal(parsed.origin,'https://flow.google.com');assert.equal(parsed.searchParams.get('rpcids'),'nzlxg');assert.equal(opts.credentials,'include');assert.equal(opts.redirect,'error');assert.equal(new URLSearchParams(opts.body).get('f.req'),'[[["nzlxg","[]",null,"generic"]]]');return{ok:true,status:200,text:async()=>JSON.stringify(mode==='ok'?[["wrb.fr","nzlxg","[12]"]]:[["er",null,null,null,null,401]])};}
});vm.runInContext(SCRIPT,context);
const check=email=>new Promise(resolve=>listener({action:'gflow-credit-check',email},{id:'gflow-test'},resolve));
(async()=>{let result=await check('example@example.test');assert.equal(result.success,true);assert.equal(result.http_status,200);assert.ok(!JSON.stringify(result).includes('fake-xsrf'));assert.equal(result.frontend,undefined);
mode='reject';result=await check('example@example.test');assert.equal(result.success,false);assert.equal(result.rpc_code,401);
result=await check('other@example.test');assert.equal(result.phase,'identity');assert.equal(calls,2);})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result=subprocess.run([shutil.which("node"),"-"],input="const SCRIPT="+json.dumps(script)+";\n"+harness,text=True,capture_output=True,encoding="utf-8",timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
