import logging
import signal
import importlib
import pkgutil

from pyrogram import asyncio, idle
from typing import List, Optional, Any, Awaitable

from . import pool
from .command import Command
from .module_extender import ModuleExtender
from .. import util


class RobOto(Command, ModuleExtender):
    "RobOto, client"
    log: logging.Logger

    def __init__(self, **kwargs) -> None:
        self.log = logging.getLogger("roboto")

        kwargs = {
            "api_id": util.config.API_ID,
            "api_hash": util.config.API_HASH,
            "session_name": util.config.STRING_SESSION or ":memory:",
            "workdir": "roboto"
        }
        super().__init__(**kwargs)

    async def start(self) -> None:
        """ Start client """
        pool.start()
        self.submodules = [
            importlib.import_module("roboto.modules." + info.name, __name__)
            for info in pkgutil.iter_modules(["roboto/modules"])
        ]
        self.load_all_modules()
        self.log.info("Starting roboto")
        await super().start()

    async def stop(self) -> None:
        """ Stop client """
        self.log.info("Stopping roboto")
        await super().stop()
        await pool.stop()

    def go(self, coro: Optional[Awaitable[Any]] = None) -> None:
        """ Start RobOto """

        lock = asyncio.Lock()
        tasks: List[asyncio.Task] = []

        async def finalized() -> None:
            async with lock:
                for task in tasks:
                    task.cancel()
                if self.is_initialized:
                    await self.stop()
                [t.cancel() for t in asyncio.all_tasks() if t is not asyncio.current_task()]
                await self.loop.shutdown_asyncgens()
                self.loop.stop()
                self.log.info("Loop stopped")

        async def shutdown(sig: signal.Signals) -> None:
            self.log.info(f"Received Stop Signal [{sig.name}], Exiting...")
            await finalized()

        for sig in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
            self.loop.add_signal_handler(
                sig, lambda sig=sig: self.loop.create_task(shutdown(sig)))

        self.loop.run_until_complete(self.start())

        try:
            if coro:
                self.log.info("Running Coroutine")
                self.loop.run_until_complete(coro)
            else:
                self.log.info("Idling")
                idle()
            self.loop.run_until_complete(finalized())
        except (asyncio.exceptions.CancelledError, RuntimeError):
            pass
        finally:
            self.loop.close()
            self.log.info("Loop closed")
