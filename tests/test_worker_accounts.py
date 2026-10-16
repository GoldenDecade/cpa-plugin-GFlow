"""余额刷新接口应返回整数结果，不能把1050误显示为0。"""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]


class WorkerAccountsTest(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_credits_preserves_integer_balance(self):
        tree = ast.parse((ROOT / "python/worker.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GFlowService")
        method = next(node for node in cls.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_refresh_credits")
        scope = {"Dict":Dict, "Any":Any}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<worker-account-method>", "exec"), scope)
        for balance in [1050, 0]:
            service = SimpleNamespace(initialize=AsyncMock(), token_manager=SimpleNamespace(refresh_credits=AsyncMock(return_value=balance)))
            result = await scope["handle_refresh_credits"](service, {"token_id":1})
            self.assertEqual(result, {"success":True, "credits":balance})
