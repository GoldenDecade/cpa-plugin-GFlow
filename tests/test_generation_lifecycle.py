"""本地假任务测试，无模型调用、无真实浏览器。"""
import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

P=Path(__file__).resolve().parents[1]
R=P
spec=importlib.util.spec_from_file_location('lifecycle',P/'python/generation_lifecycle.py')
lifecycle=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)

class Fake:
    def __init__(self,path): self.tmp_dir=path; self.messages=[]; self.started=asyncio.Event()
    def send_line(self,value): self.messages.append(value)
    async def handle_chat_completion(self,*args): self.started.set(); await asyncio.Event().wait()

class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=R/'data/tmp')
        self.service=Fake(Path(self.tmp.name))
        self.manager=lifecycle.GenerationLifecycle(self.service)
        await self.manager.start()
    async def asyncTearDown(self):
        await self.manager.shutdown()
        self.tmp.cleanup()
    async def request(self,token):
        port=self.manager.server.sockets[0].getsockname()[1]
        reader,writer=await asyncio.open_connection('127.0.0.1',port)
        writer.write(('POST /cancel HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer '+token+'\r\nContent-Length: 0\r\n\r\n').encode()); await writer.drain()
        result=await reader.read(); writer.close(); await writer.wait_closed()
        return result
    async def test_cancel_requires_task_token_and_reclaims_discovery(self):
        self.manager.submit('one',{'stream':True,'model':'gflow-nano-banana-2-lite','client_request_id':'00000000-0000-0000-0000-000000000001-0'})
        await self.service.started.wait()
        self.assertIn(b'404 Not Found',await self.request('wrong'))
        self.assertEqual(len(self.manager.controls),1)
        token=next(iter(self.manager.controls))
        self.assertIn(b'200 OK',await self.request(token))
        await asyncio.wait_for(asyncio.gather(*list(self.manager.tasks)),2)
        self.assertEqual(self.manager.controls,{})
        self.assertEqual(list(self.service.tmp_dir.glob('control-*.json')),[])
        self.assertTrue(any('cancelled' in m.get('chunk','') for m in self.service.messages))
    async def test_windows_pipe_stops_only_the_named_task(self):
        import os
        if os.name != 'nt': self.skipTest('Windows-only pipe')
        request='00000000-0000-0000-0000-000000000002-0'
        self.manager.submit('pipe-one',{'stream':True,'model':'gflow-nano-banana-2-lite','client_request_id':request})
        await self.service.started.wait()
        def send():
            with open(r'\\.\pipe\gflow-cancel-'+request,'r+b',buffering=0) as pipe: pipe.write(b'cancel\n')
        await asyncio.wait_for(asyncio.to_thread(send),2)
        await asyncio.wait_for(asyncio.gather(*list(self.manager.tasks)),2)
        self.assertEqual(self.manager.controls,{})
        self.assertTrue(any('cancelled' in m.get('chunk','') for m in self.service.messages))

    async def test_cancelling_queued_job_does_not_stop_active_job(self):
        self.manager.submit('active',{'stream':True,'model':'gflow-nano-banana-2-lite'})
        await self.service.started.wait()
        active=next(iter(self.manager.tasks))
        self.manager.submit('queued',{'stream':True,'model':'gflow-nano-banana-2-lite'})
        await asyncio.sleep(0.02)
        queued=next(task for task in self.manager.tasks if task is not active)
        queued.cancel()
        await queued
        self.assertFalse(active.done())
        self.assertEqual(len(self.manager.tasks),1)

    async def test_shutdown_stops_waiting_jobs(self):
        self.manager.submit('one',{'stream':True,'model':'gflow-nano-banana-2-lite'})
        self.manager.submit('two',{'stream':True,'model':'gflow-nano-banana-2-lite'})
        await self.service.started.wait()
        await asyncio.wait_for(self.manager.shutdown(),2)
        self.assertFalse(self.manager.tasks)

if __name__ == '__main__': unittest.main()
