import asyncio

from ...extention import RawClient


class Terminate(RawClient):
    async def terminate(self) -> None:
        if not self.no_updates:
            for _ in range(self.workers):
                self.dispatcher.updates_queue.put_nowait(None)
            for task in self.dispatcher.handler_worker_tasks:
                try:
                    await asyncio.wait_for(task, timeout=0.3)
                except asyncio.TimeoutError:
                    task.cancel()
            self.dispatcher.handler_worker_tasks.clear()
        await super().terminate()
