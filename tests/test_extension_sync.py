"""用模拟上游与数据库验证扩展同步，不读取真实账号、不消耗积分。"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, main
from unittest.mock import AsyncMock

PYTHON_DIR = Path(__file__).resolve().parents[1] / "python"
sys.path[:0] = [str(PYTHON_DIR), str(PYTHON_DIR / "flow2api")]
from extension_sync import ExtensionSyncError, classify_sync_failure, sync_extension_account


class ExtensionSyncTest(IsolatedAsyncioTestCase):
    def setUp(self):
        self.payload = {"login_account": "Example@example.test", "google_cookies": "SID=fake; __Secure-OSID=synthetic"}
        self.service = SimpleNamespace(
            initialize=AsyncMock(),
            flow_client=SimpleNamespace(st_to_at=AsyncMock(return_value={"access_token": "synthetic-at", "credits": 12, "user": {}})),
            db=SimpleNamespace(get_token_by_email=AsyncMock(return_value=None), update_token=AsyncMock()),
            token_manager=SimpleNamespace(add_token=AsyncMock(return_value=SimpleNamespace(id=7))),
        )

    async def test_first_sync_adds_account_with_browser_identity(self):
        result = await sync_extension_account(self.service, self.payload)
        self.assertEqual(result["action"], "added")
        self.assertEqual(result["token_id"], 7)
        kwargs = self.service.token_manager.add_token.call_args.kwargs
        self.assertEqual(kwargs["login_account"], "example@example.test")
        self.assertEqual(kwargs["google_cookies"], self.payload["google_cookies"])
        self.assertEqual(kwargs["protocol_mode"], "protocol")

    async def test_existing_account_updated_without_duplicate_or_auto_enable(self):
        self.service.db.get_token_by_email.return_value = SimpleNamespace(id=3, is_active=False)
        result = await sync_extension_account(self.service, self.payload)
        self.assertEqual(result["action"], "updated")
        self.service.token_manager.add_token.assert_not_awaited()
        kwargs = self.service.db.update_token.call_args.kwargs
        self.assertNotIn("is_active", kwargs)
        self.assertEqual(kwargs["credits"], 12)

    async def test_cookie_must_be_validated_before_database_write(self):
        self.service.flow_client.st_to_at.side_effect = RuntimeError("upstream error with sensitive details")
        with self.assertRaisesRegex(ValueError, "登录态验证失败") as raised:
            await sync_extension_account(self.service, self.payload)
        self.assertNotIn("sensitive", str(raised.exception))
        self.service.db.update_token.assert_not_awaited()
        self.service.token_manager.add_token.assert_not_awaited()

    async def test_reported_identity_mismatch_rejected(self):
        self.service.flow_client.st_to_at.return_value = {"access_token": "fake", "user": {"email": "another@example.test"}}
        with self.assertRaisesRegex(ValueError, "不一致"):
            await sync_extension_account(self.service, self.payload)
        self.service.db.update_token.assert_not_awaited()

    async def test_auth_error_has_actionable_code_and_no_raw_credentials(self):
        self.service.flow_client.st_to_at.side_effect = RuntimeError(
            "Flow 登录认证失败 (rpc=nzlxg, code=401) Cookie=DO_NOT_ECHO"
        )
        with self.assertRaises(ExtensionSyncError) as raised:
            await sync_extension_account(self.service, self.payload)
        result = raised.exception.result()
        self.assertEqual(result["error"]["code"], "gflow_google_auth_rejected")
        self.assertEqual(result["status_code"], 422)
        self.assertIn("同一浏览器", result["error"]["message"])
        self.assertNotIn("DO_NOT_ECHO", str(result))
        self.service.token_manager.add_token.assert_not_awaited()

    async def test_timeout_and_protocol_errors_are_distinct(self):
        for error, code, status in [
            (TimeoutError(), "gflow_upstream_timeout", 504),
            (RuntimeError("Flow frontend bootstrap metadata is unavailable"), "gflow_upstream_protocol", 502),
            (RuntimeError("Flow frontend RPC returned no payload"), "gflow_upstream_protocol", 502),
        ]:
            failure = classify_sync_failure(error).result()
            self.assertEqual(failure["error"]["code"], code)
            self.assertEqual(failure["status_code"], status)

    async def test_preparation_error_is_not_reported_as_bad_login(self):
        self.service.token_manager.add_token.side_effect = RuntimeError("project RPC failed")
        with self.assertRaises(ExtensionSyncError) as raised:
            await sync_extension_account(self.service, self.payload)
        self.assertEqual(raised.exception.code, "gflow_project_prepare_failed")
        self.assertEqual(raised.exception.stage, "prepare")
        self.assertIsNotNone(self.service.token_manager.add_token.call_args.kwargs["validated_session"])

    async def test_bad_email_and_missing_cookies_rejected_without_network(self):
        for data in [{}, {"login_account": "wrong", "google_cookies": "SID=fake"}, {"login_account": "ok@example.test", "google_cookies": "SID=fake"}]:
            with self.assertRaises(ValueError):
                await sync_extension_account(self.service, data)
        self.service.flow_client.st_to_at.assert_not_awaited()


if __name__ == "__main__":
    main()
