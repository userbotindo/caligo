import asyncio
import inspect
from typing import TYPE_CHECKING, Optional, Union

import pyrogram
from async_property import async_cached_property
from pyrogram.types import Chat, Message

from . import util

if TYPE_CHECKING:
    from .core import Bot


class Error(Exception):
    pass


class ConversationExist(Error):

    def __init__(self, msg: Optional[str] = None):
        self.msg = msg
        super().__init__(self.msg)


class ConversationTimeout(Error):
    pass


class Conversation:

    def __init__(
        self,
        bot: "Bot",
        input_chat: Union[str, int],
        timeout: int,
        max_messages: int
    ) -> None:
        self.Exist = ConversationExist
        self.Timeout = ConversationTimeout

        self.bot = bot
        self.client = self.bot.client

        self._counter = 0
        self._input_chat = input_chat
        self._max_incoming = max_messages
        self._timeout = timeout

    @async_cached_property
    async def chat(self) -> Chat:
        return await self.client.get_chat(self._input_chat)

    async def send_message(self, text, **kwargs) -> Message:
        sent = await self.client.send_message(self.chat.id, text, **kwargs)

        return sent

    async def send_file(self, document, **kwargs) -> Message:
        doc = await self.client.send_document(self.chat.id, document, **kwargs)

        return doc

    async def get_response(self, **kwargs) -> Message:
        response = await self._get_message(**kwargs)

        return response

    async def get_reply(self, **kwargs) -> Message:
        filters = pyrogram.filters.reply
        response = await self._get_message(filters, **kwargs)

        return response

    async def mark_read(self, max_id: Optional[int] = 0) -> bool:
        return await self.bot.client.read_history(self.chat.id, max_id)

    async def _get_message(self, filters=None, **kwargs) -> Message:
        if self._counter >= self._max_incoming:
            raise ValueError("Received max messages")

        fut = self.bot.CONVERSATION[self.chat.id]
        timeout = kwargs.get("timeout") or self._timeout
        before = util.time.usec()
        while True:
            after = before - util.time.usec()
            try:
                result = await asyncio.wait_for(fut.get(), timeout - after)
            except asyncio.TimeoutError:
                raise self.Timeout

            if filters is not None and callable(filters):
                ready = filters(self.bot.client, result)
                if inspect.iscoroutine(ready):
                    ready = await ready
                if not ready:
                    continue

            break

        self._counter += 1

        return result
