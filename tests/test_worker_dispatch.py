import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from worker_dispatch import ManagementDispatcher


class ManagementDispatcherTest(unittest.IsolatedAsyncioTestCase):
    async def test_status_responds_while_sync_waits_and_sync_is_not_replayed(self):
        started = asyncio.Event()
        release = asyncio.Event()
        status_ready = asyncio.Event()
        results = []
        calls = []

        async def sync(params):
            calls.append(params)
            started.set()
            await release.wait()
            return {"success": True}

        async def status(params):
            return {"total_tokens": 1}

        def send(message):
            results.append(message)
            if message["id"] == "status":
                status_ready.set()

        dispatcher = ManagementDispatcher(SimpleNamespace(
            handle_extension_sync=sync, handle_status=status, send_line=send,
        ))
        dispatcher.submit("sync", "extension_sync", {"synthetic": True})
        await asyncio.wait_for(started.wait(), 1)
        dispatcher.submit("status", "status", {})
        await asyncio.wait_for(status_ready.wait(), 1)
        self.assertEqual(results, [{"id": "status", "done": True, "result": {"total_tokens": 1}}])
        self.assertEqual(len(calls), 1)
        release.set()
        await asyncio.gather(*list(dispatcher.tasks))
        self.assertEqual(results[-1]["id"], "sync")
        await dispatcher.shutdown()

    async def test_mutating_requests_stay_serialized(self):
        started = asyncio.Event()
        release = asyncio.Event()
        order = []

        async def update(params):
            order.append(params["index"])
            started.set()
            await release.wait()
            return {"success": True}

        dispatcher = ManagementDispatcher(SimpleNamespace(handle_update_config=update, send_line=lambda message: None))
        dispatcher.submit("first", "update_config", {"index": 1})
        await asyncio.wait_for(started.wait(), 1)
        dispatcher.submit("second", "update_config", {"index": 2})
        await asyncio.sleep(0)
        self.assertEqual(order, [1])
        release.set()
        await asyncio.gather(*list(dispatcher.tasks))
        self.assertEqual(order, [1, 2])
        await dispatcher.shutdown()

    async def test_shutdown_reports_unknown_result_without_restarting_mutation(self):
        started = asyncio.Event()
        results = []

        async def sync(params):
            started.set()
            await asyncio.Event().wait()

        dispatcher = ManagementDispatcher(SimpleNamespace(handle_extension_sync=sync, send_line=results.append))
        dispatcher.submit("sync", "extension_sync", {})
        await asyncio.wait_for(started.wait(), 1)
        await dispatcher.shutdown()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["error"]["code"], "worker_stopped")
        self.assertFalse(dispatcher.tasks)


if __name__ == "__main__":
    unittest.main()
