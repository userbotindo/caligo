import asyncio
import logging
from typing import Any, Mapping, Optional

import httpx
from pyrogram.client import Client

from .command_dispatcher import CommandDispatcher
from .conversation_dispatcher import ConversationDispatcher
from .database_provider import DatabaseProvider
from .event_dispatcher import EventDispatcher
from .module_extender import ModuleExtender
from .telegram_bot import TelegramBot


class Caligo(
    TelegramBot,
    CommandDispatcher,
    DatabaseProvider,
    EventDispatcher,
    ConversationDispatcher,
    ModuleExtender,
):
    config: Mapping[str, Any]
    client: Client
    http: httpx.AsyncClient
    lock: asyncio.Lock
    log: logging.Logger
    loop: asyncio.AbstractEventLoop
    delete_after: Optional[float]
    stopping: bool

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.config = config
        self.log = logging.getLogger("Bot")
        self.loop = asyncio.get_event_loop()
        self.stopping = False
        self.delete_after = 15.0

        super().__init__()

        self.http = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60.0))

    @classmethod
    async def create_and_run(
        cls,
        config: Mapping[str, Any],
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ) -> "Caligo":
        bot = None

        if loop:
            asyncio.set_event_loop(loop)

        bot = cls(config)
        await bot.run()
        return bot

    async def stop(self) -> None:
        self.stopping = True

        self.log.info("Stopping")
        try:
            if self.loaded:
                await self.dispatch_event("stop")
                if self.client.is_connected:
                    try:
                        await self.client.stop()
                    except ConnectionError:
                        pass

                if self.helper_initialized and self.client_helper.is_connected:
                    try:
                        await self.client_helper.stop()
                    except ConnectionError:
                        pass
        finally:
            await self.db.close()
            await self.http.aclose()

        self.log.info("Running post-stop hooks")
        if self.loaded:
            await self.dispatch_event("stopped")
