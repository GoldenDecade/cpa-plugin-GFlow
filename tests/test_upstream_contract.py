"""使用虚构请求核对上游协议与插件边界，不调用 Google。"""
import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python/flow2api"))

from src.services.flow_client import FlowClient


class UpstreamContractTest(unittest.TestCase):
    def test_pinned_sources_are_unchanged(self):
        manifest = json.loads((ROOT / "python/flow2api/upstream.json").read_text(encoding="utf-8"))
        for name, record in manifest["files"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),record["sha256"])

    def test_image_request_retains_upstream_fourteen_slots(self):
        client = FlowClient(None)
        request = client._build_frontend_image_generation_argument(
            project_id="11111111-1111-1111-1111-111111111111", prompt="synthetic",
            model_name="BELUGA", aspect_ratio="IMAGE_ASPECT_RATIO_LANDSCAPE",
            recaptcha_token="synthetic-token", session_id="synthetic-session",
        )[1][0]
        self.assertEqual(len(request),14)
        self.assertEqual(request[5],"BELUGA")
        self.assertEqual(request[12],"synthetic-session")

    def test_google_denial_is_a_failure(self):
        client = FlowClient(None)
        frames = [[["wrb.fr","ogiZ0b",None,None,None,["PUBLIC_ERROR_UNUSUAL_ACTIVITY"]]]]
        with self.assertRaisesRegex(RuntimeError,"PUBLIC_ERROR_UNUSUAL_ACTIVITY"):
            client._raise_batchexecute_error(frames,"ogiZ0b")


class UpstreamTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_body_and_cookie_reach_upstream_transport_once(self):
        client=FlowClient(None)
        response=SimpleNamespace(status_code=200,text="synthetic-response")
        session=SimpleNamespace(post=AsyncMock(return_value=response))
        class Session:
            async def __aenter__(self): return session
            async def __aexit__(self,*args): return False
        with patch("src.services.flow_client.AsyncSession",return_value=Session()):
            result=await client._make_text_request(
                "POST","https://flow.google.com/_/AiSandboxAngularFrontend/data/batchexecute",
                headers={"Cookie":"SID=synthetic; OSID=fake"} ,raw_body="f.req=synthetic",
                redact_sensitive_logs=True,
            )
        self.assertEqual(result,"synthetic-response")
        session.post.assert_awaited_once()
        self.assertEqual(session.post.call_args.kwargs["data"],"f.req=synthetic")
        self.assertEqual(session.post.call_args.kwargs["headers"]["Cookie"],"SID=synthetic; OSID=fake")

    async def test_worker_uses_model_adapter_before_upstream_handler(self):
        import worker
        service=worker.GFlowService.__new__(worker.GFlowService)
        service.initialize=AsyncMock()
        service.token_manager=SimpleNamespace(get_active_tokens=AsyncMock(return_value=[object()]))
        service.send_line=lambda value:None
        service.tmp_dir=ROOT/".tools"
        with patch("src.api.routes._collect_non_stream_result",AsyncMock(return_value="{}")) as generate:
            await service.handle_chat_completion("test",{
                "model":"gflow-nano-banana-2.1",
                "messages":[{"role":"user","content":"synthetic"}],
                "aspect_ratio":"16:9", "image_size":"2K",
            })
        generate.assert_awaited_once()
        self.assertEqual(generate.call_args.args[0],"gemini-3.1-flash-image-landscape-2k")
