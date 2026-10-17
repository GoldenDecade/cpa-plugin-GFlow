"""Cookie 作用域回归；只用合成值，不读取账号。"""
import ast
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"python"),str(ROOT/"python/flow2api")]
import importlib.util
utility=ROOT/"python/flow2api/src/services/browser_cookie_utils.py"
spec=importlib.util.spec_from_file_location("cookie_utils_under_test",utility)
utils=importlib.util.module_from_spec(spec); spec.loader.exec_module(utils)
source=ROOT/"python/flow2api/src/services/personal_cookie_policy.py"
namespace={"__name__":"cookie_policy_under_test","parse_browser_cookie_payload":utils.parse_browser_cookie_payload,"merge_browser_cookie_payloads":utils.merge_browser_cookie_payloads}
exec(compile(source.read_text(encoding="utf-8").replace("    from .browser_cookie_utils import parse_browser_cookie_payload","").replace("    from .browser_cookie_utils import merge_browser_cookie_payloads",""),str(source),"exec"),namespace)
scoped_personal_cookies=namespace["scoped_personal_cookies"]
merge_personal_cookie_payloads=namespace["merge_personal_cookie_payloads"]

class CookieRegression(unittest.TestCase):
    def test_raw_header_places_login_on_parent_and_osid_only_on_flow(self):
        result=scoped_personal_cookies("SID=fake; OSID=flow-only")
        self.assertEqual(result[0]["domain"],".google.com")
        self.assertEqual(result[1]["url"],"https://flow.google.com/")
        self.assertNotIn("domain",result[1])

    def test_explicit_scope_and_attributes_are_preserved(self):
        original=[{"name":"OSID","value":"fake","url":"https://flow.google.com/","path":"/","secure":True,"httpOnly":True},
                  {"name":"SID","value":"fake-parent","domain":".google.com","sameSite":"Lax","path":"/","secure":True}]
        self.assertEqual(scoped_personal_cookies(json.dumps(original)),original)

    def test_legacy_three_site_mirrors_do_not_leak_osid_to_google(self):
        original=[{"name":name,"value":"fake-"+name,"url":"https://"+host+"/","path":"/"}
                  for name in ["SID","OSID"] for host in ["flow.google.com","www.google.com","www.recaptcha.net"]]
        result=scoped_personal_cookies(json.dumps(original))
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]["domain"],".google.com")
        self.assertEqual(result[1]["url"],"https://flow.google.com/")

class BrowserExportRegression(unittest.TestCase):
    def test_equal_flow_and_parent_login_cookies_do_not_repeat_in_request(self):
        original = [
            {"name": "SID", "value": "same", "url": "https://flow.google.com/", "path": "/"},
            {"name": "SID", "value": "same", "domain": ".google.com", "path": "/"},
            {"name": "OSID", "value": "flow", "url": "https://flow.google.com/", "path": "/"},
        ]
        result = scoped_personal_cookies(json.dumps(original))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["domain"], ".google.com")
        self.assertEqual(result[1]["name"], "OSID")

    def test_distinct_host_and_parent_values_remain_scoped(self):
        original = [
            {"name": "SID", "value": "host", "url": "https://flow.google.com/", "path": "/"},
            {"name": "SID", "value": "parent", "domain": ".google.com", "path": "/"},
        ]
        self.assertEqual(scoped_personal_cookies(json.dumps(original)), original)



class PersonalPersistenceRegression(unittest.TestCase):
    def test_raw_header_is_scoped_before_browser_refresh_merge(self):
        merged = merge_personal_cookie_payloads(
            "SID=old-parent; __Secure-3PSID=old-secure; OSID=flow-only",
            [
                {"name": "SID", "value": "new-parent", "domain": ".google.com", "path": "/", "httpOnly": True},
                {"name": "__Secure-3PSID", "value": "new-secure", "domain": ".google.com", "path": "/", "secure": True},
                {"name": "OSID", "value": "flow-new", "domain": "flow.google.com", "path": "/"},
            ],
        )
        self.assertEqual(utils.cookie_pairs_for_url(merged), [
            ("SID", "new-parent"), ("__Secure-3PSID", "new-secure"), ("OSID", "flow-new"),
        ])
        stored = json.loads(merged)
        self.assertTrue(stored[0]["httpOnly"])
        self.assertEqual(stored[0]["domain"], ".google.com")
        self.assertNotIn(("OSID", "flow-new"), utils.cookie_pairs_for_url(merged, "https://accounts.google.com/"))

    def test_real_host_path_values_are_preserved_and_updated_by_scope(self):
        base = [
            {"name": "SID", "value": "parent", "domain": ".google.com", "path": "/"},
            {"name": "SID", "value": "host", "url": "https://flow.google.com/", "path": "/"},
            {"name": "SID", "value": "project", "url": "https://flow.google.com/", "path": "/project"},
            {"name": "OSID", "value": "flow", "url": "https://flow.google.com/", "path": "/"},
        ]
        merged = merge_personal_cookie_payloads(json.dumps(base), [
            {"name": "SID", "value": "project-new", "domain": "flow.google.com", "path": "/project"},
        ])
        self.assertEqual(len(json.loads(merged)), 4)
        self.assertEqual(utils.cookie_pairs_for_url(merged, "https://flow.google.com/project/1"), [
            ("SID", "project-new"), ("SID", "parent"), ("SID", "host"), ("OSID", "flow"),
        ])
        self.assertEqual(utils.cookie_pairs_for_url(merged, "https://accounts.google.com/"), [("SID", "parent")])

    def test_unrelated_snapshot_host_does_not_replace_flow_session(self):
        merged = merge_personal_cookie_payloads("SID=parent; OSID=flow-session", [
            {"name": "OSID", "value": "accounts-session", "domain": "accounts.google.com", "path": "/"},
        ])
        self.assertIn(("OSID", "flow-session"), utils.cookie_pairs_for_url(merged))
        self.assertNotIn(("OSID", "accounts-session"), utils.cookie_pairs_for_url(merged))
        self.assertIn(("OSID", "accounts-session"), utils.cookie_pairs_for_url(merged, "https://accounts.google.com/"))

    def test_equal_legacy_copy_is_removed_but_different_host_value_is_kept(self):
        browser_export = [
            {"name": "SID", "value": "same", "domain": ".google.com", "path": "/"},
            {"name": "SID", "value": "same", "domain": "flow.google.com", "path": "/"},
            {"name": "SID", "value": "other-host", "domain": "www.google.com", "path": "/"},
            {"name": "OSID", "value": "flow", "domain": "flow.google.com", "path": "/"},
        ]
        merged = merge_personal_cookie_payloads("", browser_export)
        self.assertEqual(len(json.loads(merged)), 3)
        self.assertEqual(utils.cookie_pairs_for_url(merged), [("SID", "same"), ("OSID", "flow")])
        self.assertEqual(merge_personal_cookie_payloads(merged, browser_export), merged)


class PersonalPersistenceLifecycleRegression(unittest.IsolatedAsyncioTestCase):
    async def test_browser_export_persist_reinject_and_http_header(self):
        # 提取真实持久化方法，替换浏览器/数据库外设；不启动浏览器或读取账号。
        browser_source = ROOT/"python/flow2api/src/services/browser_captcha_personal.py"
        tree = ast.parse(browser_source.read_text(encoding="utf-8"))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)
                      and node.name == "_persist_context_cookies_to_token")
        method.returns = None
        for arg in method.args.args + method.args.kwonlyargs:
            arg.annotation = None
        method.decorator_list = []
        ns = {
            "merge_personal_cookie_payloads": merge_personal_cookie_payloads,
            "normalize_cookie_storage_text": utils.normalize_cookie_storage_text,
            "debug_logger": SimpleNamespace(log_info=lambda *args: None, log_warning=lambda *args: None),
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                     str(browser_source), "exec"), ns)

        raw_header = "SID=old-parent; __Secure-3PSID=old-secure; OSID=flow-only; NID=old-nid; SIDCC=old-sidcc"
        injected = scoped_personal_cookies(raw_header)
        exported = []
        for item in injected:
            browser_cookie = dict(item)
            if "url" in browser_cookie:
                browser_cookie.pop("url")
                browser_cookie["domain"] = "flow.google.com"
            if browser_cookie["name"] == "SID":
                browser_cookie["value"] = "browser-refreshed"
            exported.append(browser_cookie)

        # 模拟浏览器在原注入副本之外刷新了真实父域 NID/SIDCC。
        exported.extend([
            {"name": "NID", "value": "browser-nid", "domain": ".google.com", "path": "/"},
            {"name": "SIDCC", "value": "browser-sidcc", "domain": ".google.com", "path": "/"},
        ])

        class FakeDB:
            value = raw_header
            async def update_token(self, token_id, **updates):
                self.value = updates["google_cookies"]

        db = FakeDB()
        async def load_cookie(_token_id):
            return db.value
        async def get_cookies(**_kwargs):
            return exported
        service = SimpleNamespace(
            db=db,
            _normalize_token_key=lambda token_id: str(token_id),
            _get_browser_cookies=get_cookies,
            _serialize_browser_cookie_for_storage=lambda cookie: cookie,
            _load_token_cookie=load_cookie,
            _normalize_cookie_signature=utils.build_cookie_signature,
        )
        resident = SimpleNamespace(tab=True, browser_context_id="synthetic-context",
                                   token_id=1, slot_id="synthetic-slot", cookie_signature=None)
        self.assertTrue(await ns["_persist_context_cookies_to_token"](service, resident, 1, label="offline"))
        persisted = db.value
        reinjected = scoped_personal_cookies(persisted)
        self.assertEqual(len(reinjected), 5)
        self.assertCountEqual(
            utils.serialize_cookie_header_for_url(json.dumps(reinjected)).split("; "),
            ["SID=browser-refreshed", "__Secure-3PSID=old-secure", "OSID=flow-only",
             "NID=browser-nid", "SIDCC=browser-sidcc"],
        )
        account_header = utils.serialize_cookie_header_for_url(
            json.dumps(reinjected), "https://accounts.google.com/")
        self.assertCountEqual(
            account_header.split("; "),
            ["SID=browser-refreshed", "__Secure-3PSID=old-secure", "NID=browser-nid", "SIDCC=browser-sidcc"],
        )
        self.assertNotIn("OSID", account_header)
        exported[:] = reinjected
        self.assertTrue(await ns["_persist_context_cookies_to_token"](service, resident, 1, label="offline-again"))
        self.assertEqual(db.value, persisted)

if __name__=="__main__": unittest.main()
