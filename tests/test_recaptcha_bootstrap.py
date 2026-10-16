"""执行真实注入脚本，模拟启用 Trusted Types 的页面。"""
import ast
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
class ScriptRegression(unittest.TestCase):
    def test_score_key_executes_without_rendering_the_document_root(self):
        import importlib.util
        source=ROOT/"python/flow2api/src/services/recaptcha_runtime.py"
        spec=importlib.util.spec_from_file_location("runtime_under_test",source)
        runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
        script=runtime.build_recaptcha_execute_script("synthetic-key","IMAGE_GENERATION",1000)
        node=os.environ.get("GFLOW_TEST_NODE") or shutil.which("node")
        if not node: self.skipTest("Node.js required")
        harness=r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const enterprise={render(){throw new Error('Must not render document root')},execute(key,options){assert.equal(key,'synthetic-key');assert.equal(options.action,'IMAGE_GENERATION');return Promise.resolve('synthetic-token')}};
const context=vm.createContext({window:{grecaptcha:{enterprise},__flow2apiTrustedRecaptchaExecute:enterprise.execute},location:{href:'https://flow.google.com/projects'},setTimeout,clearTimeout});
Promise.resolve(vm.runInContext(SOURCE,context)).then(result=>{assert.equal(result.ok,true);assert.equal(result.token,'synthetic-token')}).catch(e=>{console.error(e);process.exitCode=1});
"""
        subprocess.run([node,"-e",harness.replace("SOURCE",json.dumps(script))],check=True,capture_output=True,text=True)

    def test_fingerprint_script_executes_instead_of_returning_a_function(self):
        source=ROOT/"python/flow2api/src/services/browser_captcha_personal.py"
        tree=ast.parse(source.read_text(encoding="utf-8"))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="BrowserCaptchaService")
        method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="_extract_tab_fingerprint")
        call=next(n for n in ast.walk(method) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=="_tab_evaluate")
        script=call.args[1].value
        node=os.environ.get("GFLOW_TEST_NODE") or shutil.which("node")
        if not node: self.skipTest("Node.js required")
        harness="""
const vm=require('node:vm'),assert=require('node:assert/strict');
const context={navigator:{userAgent:'synthetic-UA',language:'en',languages:['en']},window:{},screen:{},Intl};
const result=vm.runInNewContext(SOURCE,context);
assert.equal(typeof result,'object');
assert.equal(result.user_agent,'synthetic-UA');
"""
        subprocess.run([node,"-e",harness.replace("SOURCE",json.dumps(script))],check=True,capture_output=True,text=True)

    def test_bootstrap_urls_enable_upstream_trusted_types(self):
        source=ROOT/"python/flow2api/src/services/browser_captcha_personal.py"
        tree=ast.parse(source.read_text(encoding="utf-8"))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="BrowserCaptchaService")
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=="_get_recaptcha_bootstrap_candidate_urls")
        namespace={"Optional":__import__("typing").Optional}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(source),"exec"),namespace)
        urls=namespace["_get_recaptcha_bootstrap_candidate_urls"](None,"recaptcha/enterprise.js","synthetic-key")
        self.assertTrue(urls[0].startswith("https://www.google.com/"))
        self.assertTrue(all("trustedtypes=true" in url for url in urls))

    def test_script_url_uses_a_constrained_trusted_types_policy(self):
        source=ROOT/"python/flow2api/src/services/browser_captcha_personal.py"
        tree=ast.parse(source.read_text(encoding="utf-8"))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=="BrowserCaptchaService")
        method=next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="_inject_recaptcha_bootstrap_script")
        code=ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name="Subject",bases=[],keywords=[],body=[method],decorator_list=[])],type_ignores=[]))
        namespace={"json":json,"debug_logger":SimpleNamespace(log_info=lambda *a:None)}
        exec(compile(code,str(source),"exec"),namespace)
        subject=namespace["Subject"]()
        subject._get_recaptcha_bootstrap_candidate_urls=lambda *a,**k:["https://www.recaptcha.net/recaptcha/enterprise.js?render=fake"]
        captured=[]
        async def evaluate(tab,script,**kwargs): captured.append(script)
        subject._tab_evaluate=evaluate
        asyncio.run(subject._inject_recaptcha_bootstrap_script(None,"recaptcha/enterprise.js","fake","regression"))
        node=os.environ.get("GFLOW_TEST_NODE") or shutil.which("node")
        if not node: self.skipTest("Node.js required to execute captured browser JavaScript")
        harness=r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const appended=[];
const context=vm.createContext({URL,Date,window:{trustedTypes:true},
 trustedTypes:{createPolicy(name,rules){return {createScriptURL(value){return {trusted:true,value:rules.createScriptURL(value)}}}}},
 document:{querySelector(selector){return selector==='script[nonce]'?{nonce:'synthetic-page-nonce'}:null},querySelectorAll(){return []},
 head:{appendChild(node){appended.push(node)}},createElement(){return {set src(value){if(!value.trusted)throw new TypeError('TrustedScriptURL required');this.url=value.value},remove(){}}}},
 setTimeout(){return 1},clearTimeout(){}});
vm.runInContext(SOURCE,context);
assert.equal(appended.length,1);
assert.equal(appended[0].nonce,'synthetic-page-nonce');
assert.equal(context.window.__flow2apiRecaptchaBootstrapState.status,'loading');
assert.throws(()=>context.window.__flow2apiRecaptchaScriptPolicy.createScriptURL('https://attacker.test/recaptcha/enterprise.js'));
assert.throws(()=>context.window.__flow2apiRecaptchaScriptPolicy.createScriptURL('https://www.google.com/unrelated.js'));
"""
        command=harness.replace("SOURCE",json.dumps(captured[0]))
        subprocess.run([node,"-e",command],check=True,capture_output=True,text=True)

if __name__=="__main__": unittest.main()
