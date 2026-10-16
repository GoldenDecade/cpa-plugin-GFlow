"""Cookie 作用域回归；只用合成值，不读取账号。"""
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"python"),str(ROOT/"python/flow2api")]
import importlib.util
utility=ROOT/"python/flow2api/src/services/browser_cookie_utils.py"
spec=importlib.util.spec_from_file_location("cookie_utils_under_test",utility)
utils=importlib.util.module_from_spec(spec); spec.loader.exec_module(utils)
source=ROOT/"python/flow2api/src/services/personal_cookie_policy.py"
namespace={"__name__":"cookie_policy_under_test","parse_browser_cookie_payload":utils.parse_browser_cookie_payload}
exec(compile(source.read_text(encoding="utf-8").replace("    from .browser_cookie_utils import parse_browser_cookie_payload",""),str(source),"exec"),namespace)
scoped_personal_cookies=namespace["scoped_personal_cookies"]

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

if __name__=="__main__": unittest.main()
