"""Cookie 作用域回归；只用合成值，不读取账号。"""
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"python"),str(ROOT/"python/flow2api")]
from src.services.personal_cookie_policy import scoped_personal_cookies

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

if __name__=="__main__": unittest.main()
