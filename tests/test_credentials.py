"""只使用虚构 Cookie，禁止网络调用。"""
import sys
from pathlib import Path
import unittest

PYTHON_DIR = Path(__file__).resolve().parents[1] / "python"
sys.path[:0] = [str(PYTHON_DIR), str(PYTHON_DIR / "flow2api")]
from credentials import normalize_account_input


class CredentialInputTest(unittest.TestCase):
    def test_raw_session_token(self):
        self.assertEqual(normalize_account_input(None, "dummy.session.value"), ("dummy.session.value", ""))

    def test_complete_cookie_extracts_st(self):
        cookie = "SID=fake; __Secure-next-auth.session-token=dummy%2Etoken"
        self.assertEqual(normalize_account_input(None, "Cookie: " + cookie), ("dummy.token", cookie))

    def test_modern_google_cookie_does_not_become_session_token(self):
        cookie = "SID=fake; __Secure-OSID=synthetic"
        self.assertEqual(normalize_account_input(None, cookie), ("", cookie))

    def test_cookie_array(self):
        raw = '[{"name":"next-auth.session-token","value":"dummy","domain":".example.test"}]'
        st, cookie = normalize_account_input(None, raw)
        self.assertEqual(st, "dummy")
        self.assertIn("next-auth.session-token", cookie)

    def test_updater_json(self):
        st, cookie = normalize_account_input(None, '{"st":"fake.st","google_cookies":"SID=fake; OSID=fake"}')
        self.assertEqual(st, "fake.st")
        self.assertEqual(cookie, "SID=fake; OSID=fake")

    def test_explicit_st_takes_priority(self):
        self.assertEqual(normalize_account_input("explicit", "next-auth.session-token=from-cookie")[0], "explicit")

    def test_invalid_or_empty_input(self):
        for value in ["", "{broken"]:
            with self.assertRaises(ValueError):
                normalize_account_input(None, value)

    def test_reject_http_request_dump(self):
        with self.assertRaises(ValueError):
            normalize_account_input(None, "SID=fake\nHost: example.test".replace("\n", chr(10)))


if __name__ == "__main__":
    unittest.main()
