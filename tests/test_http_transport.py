"""TLS 重连不得重复提交已发送或未知结果的生成请求。"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python/flow2api"))
from curl_cffi.const import CurlHttpVersion, CurlInfo
from curl_cffi.requests.exceptions import RequestException
from src.services.http_transport import request_with_tls_recovery


def failure(code=35, uploaded=0, downloaded=0, redirects=0, status=0, known=True):
    response = SimpleNamespace(status_code=status, infos={
        CurlInfo.SIZE_UPLOAD_T: uploaded, CurlInfo.SIZE_DOWNLOAD_T: downloaded,
        CurlInfo.REDIRECT_COUNT: redirects,
    }) if known else None
    return RequestException("synthetic TLS error", code=code, response=response)


class TransportTest(unittest.IsolatedAsyncioTestCase):
    async def send(self, errors):
        self.posts = AsyncMock(side_effect=errors)
        self.options = []
        outer = self
        class Session:
            def __init__(self, **kwargs): outer.options.append(kwargs)
            async def __aenter__(self): return SimpleNamespace(post=outer.posts)
            async def __aexit__(self, *args): return False
        return await request_with_tls_recovery(
            Session, "POST", "https://flow.google.com/synthetic",
            headers={"Cookie":"synthetic"}, data="synthetic-body",
            proxy="http://127.0.0.1:7897", timeout=5, impersonate="chrome",
        )

    async def test_recovers_only_proven_unsent_tls_handshake(self):
        expected = SimpleNamespace(status_code=200)
        self.assertIs(await self.send([failure(), expected]), expected)
        first, second = [call.kwargs for call in self.posts.call_args_list]
        self.assertNotIn("http_version", first)
        self.assertEqual(second["http_version"], CurlHttpVersion.V1_1)
        for field in ["headers","data","proxy","impersonate"]:
            self.assertEqual(first[field], second[field])
        self.assertLessEqual(second["timeout"], first["timeout"])
        self.assertNotIn("verify", second)

    async def test_never_replays_sent_or_unknown_request(self):
        for error in [
            failure(uploaded=20), failure(downloaded=10), failure(redirects=1),
            failure(status=503), failure(known=False), failure(code=28), failure(code=56),
        ]:
            with self.subTest(error=error):
                with self.assertRaises(RequestException): await self.send([error])
                self.assertEqual(self.posts.await_count, 1)

    async def test_reconnection_is_bounded_to_one(self):
        with self.assertRaises(RequestException): await self.send([failure(), failure()])
        self.assertEqual(self.posts.await_count, 2)

    async def test_google_denial_is_never_replayed(self):
        denied = SimpleNamespace(status_code=403, text="PUBLIC_ERROR_UNUSUAL_ACTIVITY")
        self.assertIs(await self.send([denied]), denied)
        self.assertEqual(self.posts.await_count, 1)

    async def test_cancellation_is_not_retried(self):
        import asyncio
        with self.assertRaises(asyncio.CancelledError): await self.send([asyncio.CancelledError()])
        self.assertEqual(self.posts.await_count, 1)


if __name__ == "__main__":
    unittest.main()
