import asyncio
import sys
import traceback


class ManagementDispatcher:
    def __init__(self, service):
        self.service = service
        self.tasks = set()
        self.mutations = asyncio.Lock()

    def submit(self, request_id, command, params):
        task = asyncio.create_task(self.run(request_id, command, params))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def run(self, request_id, command, params):
        try:
            handler = getattr(self.service, "handle_" + command, None)
            if handler is None:
                raise ValueError("Unknown command: " + command)
            if command in {"ping", "status", "list_tokens", "list_models", "get_config"}:
                result = await handler(params)
            else:
                async with self.mutations:
                    result = await handler(params)
            self.service.send_line({"id": request_id, "done": True, "result": result})
        except asyncio.CancelledError:
            self.service.send_line({
                "id": request_id, "done": True,
                "error": {"code": "worker_stopped", "message": "GFlow backend stopped; operation result may be unknown", "status_code": 503},
            })
        except Exception as error:
            sys.stderr.write(f"[GFlowService] Error in {command}: {traceback.format_exc()}\n")
            self.service.send_line({"id": request_id, "done": True, "error": {"message": str(error)}})

    async def shutdown(self):
        pending = list(self.tasks)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
