import aiohttp
import asyncio
import logging

import pyrogram

from typing import Optional

from .telegram_bot import TelegramBot


class Bot(TelegramBot):
    client: pyrogram.Client
    http: aiohttp.ClientSession
    lock: asyncio.locks.Lock
    log: logging.Logger
    loop: asyncio.AbstractEventLoop
    stopping: bool

    def __init__(self):
        self.log = logging.getLogger("Bot")
        self.loop = asyncio.get_event_loop()
        self.stopping = False

        super().__init__()

        self.http = aiohttp.ClientSession()

    @classmethod
    async def create_and_run(
        cls, *, loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> "Bot":
        bot = None

        if loop:
            asyncio.set_event_loop(loop)

        try:
            bot = cls()
            await bot.run()
            return bot
        finally:
            if bot is None or (bot is not None and not bot.stopping):
                asyncio.get_event_loop().stop()

    async def stop(self) -> None:
        self.stopping = True

        self.log.info("Stopping")
        await self.http.close()
        self.log.info("Running post-stop hooks")

        async def finalize() -> None:
            lock = asyncio.Lock()

            async with lock:
                if self.client.is_initialized:
                    await self.client.stop()
                for task in asyncio.all_tasks():
                    if not asyncio.current_task():
                        task.cancel()
                await self.loop.shutdown_asyncgens()
                self.loop.stop()
        await finalize()
