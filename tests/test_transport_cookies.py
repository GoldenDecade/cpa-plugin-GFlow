"""传输前不得丢失浏览器合法的同名 Cookie。"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python/flow2api"))
from src.services.flow_client import FlowClient

class TransportCookiesTest(unittest.TestCase):
    def test_duplicate_cookie_order_survives_empty_fingerprint_cookies(self):
        header = "SID=host-specific; SID=parent-domain; __Secure-OSID=fake-flow"
        for extras in (None, {}):
            self.assertEqual(FlowClient._merge_cookie_header(header, extras), header)

    def test_runtime_cookies_append_without_overwriting_or_collapsing(self):
        header = "SID=host-specific; SID=parent-domain"
        self.assertEqual(FlowClient._merge_cookie_header(header, {"SID":"old", "OSID":"runtime"}), header + "; OSID=runtime")


class TransportRequestTest(unittest.IsolatedAsyncioTestCase):
    async def test_browser_fingerprint_keeps_duplicate_cookie_header_in_actual_post(self):
        client = FlowClient(None)
        client._set_request_fingerprint({"user_agent":"Mozilla/5.0 Chrome/154.0.0.0"})
        response = SimpleNamespace(status_code=200, text="synthetic-response")
        session = SimpleNamespace(post=AsyncMock(return_value=response))
        class Session:
            async def __aenter__(self): return session
            async def __aexit__(self, *args): return False
        header = "SID=host-specific; SID=parent-domain; __Secure-OSID=fake-flow"
        with patch("src.services.flow_client.AsyncSession", return_value=Session()):
            result = await client._make_text_request("POST", "https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute", headers={"Cookie":header}, raw_body="f.req=synthetic", redact_sensitive_logs=True)
        self.assertEqual(result,"synthetic-response")
        self.assertEqual(session.post.call_args.kwargs["headers"]["Cookie"],header)

class SingleAttemptRegression(unittest.TestCase):
    def test_captcha_failure_cannot_expand_an_explicit_single_attempt(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        client=FlowClient(None)
        with patch("src.services.flow_client.config", SimpleNamespace(flow_max_retries=1,browser_captcha_generation_retries=6)):
            self.assertEqual(client._resolve_generation_retry_budget(1, "reCAPTCHA evaluation failed"),1)

class FrontendSessionRegression(unittest.TestCase):
    def test_frontend_marker_does_not_refresh_immediately(self):
        from datetime import datetime,timedelta,timezone
        from types import SimpleNamespace
        from src.services.token_manager import TokenManager
        manager=TokenManager.__new__(TokenManager)
        manager.flow_client=SimpleNamespace(FRONTEND_ACCESS_TOKEN="frontend-marker")
        token=SimpleNamespace(id=1,at="frontend-marker",at_expires=datetime.now(timezone.utc)+timedelta(minutes=55))
        self.assertFalse(manager._should_refresh_at(token))
        token.at_expires=datetime.now(timezone.utc)+timedelta(minutes=3)
        self.assertTrue(manager._should_refresh_at(token))

    def test_rpc_uses_the_same_scoped_cookie_policy_as_the_browser(self):
        import asyncio,json
        client=FlowClient(None)
        original=[{"name":name,"value":"fake-"+name,"url":"https://"+host+"/","path":"/"}
                  for name in ["SID","OSID"] for host in ["flow.google.com","www.google.com","www.recaptcha.net"]]
        result=json.loads(asyncio.run(client._resolve_flow_frontend_cookie_storage(json.dumps(original))))
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]["domain"],".google.com")
        self.assertEqual(result[1]["url"],"https://flow.google.com/")
