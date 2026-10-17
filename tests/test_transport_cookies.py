"""传输前不得丢失浏览器合法的同名 Cookie。"""
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python/flow2api"))
from src.services.flow_client import FlowClient

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
