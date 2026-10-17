"""查额使用模拟上游，不刷新会话或启动浏览器；失败必须区别于真实零余额。"""
import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"python"),str(ROOT/"python/flow2api")]


class WorkerAccountsTest(unittest.IsolatedAsyncioTestCase):
    def make_service(self, *, balance=1050, error=None, exists=True):
        tree = ast.parse((ROOT/"python/worker.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=="GFlowService")
        method = next(n for n in cls.body if isinstance(n,ast.AsyncFunctionDef)and n.name=="handle_refresh_credits")
        scope={"Dict":Dict,"Any":Any}
        exec(compile(ast.Module(body=[method],type_ignores=[]),"<worker-credit-method>","exec"),scope)
        token=SimpleNamespace(at="synthetic",google_cookies="SID=fake")
        client=SimpleNamespace(get_credits=AsyncMock(return_value={"credits":balance,"userPaygateTier":"synthetic"},side_effect=error))
        service=SimpleNamespace(initialize=AsyncMock(),flow_client=client,
            db=SimpleNamespace(get_token=AsyncMock(return_value=token if exists else None),update_token=AsyncMock()),
            token_manager=SimpleNamespace(refresh_credits=AsyncMock(side_effect=AssertionError("manual credit lookup must not refresh login"))))
        return service,scope["handle_refresh_credits"]

    async def test_real_zero_and_integer_balance_are_successful(self):
        for balance in [1050,0]:
            service,method=self.make_service(balance=balance)
            self.assertEqual(await method(service,{"token_id":1}),{"success":True,"credits":balance})
            self.assertEqual(service.db.update_token.await_args.kwargs["credits"],balance)
            service.token_manager.refresh_credits.assert_not_awaited()

    async def test_rejected_session_does_not_report_zero_or_overwrite_balance(self):
        service,method=self.make_service(error=RuntimeError("Flow 登录认证失败 (rpc=nzlxg, code=401)"))
        result=await method(service,{"token_id":1})
        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"],401)
        self.assertEqual(result["error"]["code"],"gflow_session_expired")
        self.assertNotIn("credits",result)
        service.db.update_token.assert_not_awaited()
        service.token_manager.refresh_credits.assert_not_awaited()

    async def test_network_failure_does_not_report_zero(self):
        service,method=self.make_service(error=TimeoutError("synthetic timeout"))
        result=await method(service,{"token_id":1})
        self.assertFalse(result["success"])
        self.assertEqual(result["status_code"],504)
        service.db.update_token.assert_not_awaited()
        service.token_manager.refresh_credits.assert_not_awaited()

    async def test_unknown_account_does_not_call_upstream(self):
        service,method=self.make_service(exists=False)
        result=await method(service,{"token_id":999})
        self.assertEqual(result["status_code"],404)
        service.flow_client.get_credits.assert_not_awaited()
