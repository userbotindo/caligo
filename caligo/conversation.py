import asyncio
import inspect
import logging
from typing import TYPE_CHECKING, Optional, Union

import pyrogram
from async_property import async_cached_property
from pyrogram.raw import functions

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

    log: logging.Logger

    def __init__(
        self,
        bot: "Bot",
        input_chat: Union[str, int],
        timeout: int,
        max_messages: int
    ):
        self.bot = bot
        self.log = self.bot.log

        self._input_chat = input_chat
        self._timeout = timeout
        self._max_incoming = max_messages
        self._counter = 0

        self.Exist = ConversationExist
        self.Timeout = ConversationTimeout

    @async_cached_property
    async def chat(self) -> pyrogram.types.Chat:
        return await self.bot.client.get_chat(self._input_chat)

    async def send_message(self, text, **kwargs) -> pyrogram.types.Message:
        sent = await self.bot.client.send_message(self.chat.id, text, **kwargs)

        return sent

    async def send_file(self, document, **kwargs) -> pyrogram.types.Message:
        file = await self.bot.client.send_document(self.chat.id, document, **kwargs)

        return file

    async def get_response(self, **kwargs) -> pyrogram.types.Message:
        response = await self._get_message()

        return response

    async def get_reply(self, **kwargs) -> pyrogram.types.Message:
        filters = pyrogram.filters.reply
        response = await self._get_message(filters)

        return response

    async def mark_read(self, **kwargs) -> None:
        await asyncio.gather(
            self.bot.client.send(functions.messages.ReadMentions(
                peer=await self.bot.client.resolve_peer(self.chat.id))),
            self.bot.client.read_history(self.chat.id, **kwargs)
        )

    async def _get_message(self, filters=None, **kwargs) -> pyrogram.types.Message:
        if self._counter >= self._max_incoming:
            raise ValueError("Received max messages")

        fut = self.bot.CONVERSATION[self.chat.id]
        timeout = kwargs.get("timeout") or self._timeout

        before = util.time.usec()
        while True:
            after = util.time.usec()
            el_us = before - after
            try:
                result = await self._get_result(fut, timeout - el_us)
            except asyncio.TimeoutError:
                raise self.Timeout

            if filters is not None and callable(filters):
                ready = filters(self.bot.client, result)
                if inspect.iscoroutine(ready):
                    ready = await ready
                if not ready:
                    continue

            break

        return result

    async def _get_result(
        self,
        future: asyncio.Queue,
        due: Union[int, float],
        **kwargs
    ) -> pyrogram.types.Message:
        return await asyncio.wait_for(future.get(), max(0.1, due))

    async def __aenter__(self) -> "Conversation":
        await self.chat  # Load the chat entity

        if self.chat.type in ["bot", "private"]:
            self.chat.name = self.chat.first_name
        else:
            self.chat.name = self.chat.title

        if self.chat.id in self.bot.CONVERSATION:
            raise self.Exist(f"Conversation with '{self.chat.name}' exist")

        self.log.info(f"Opening conversation with '{self.chat.name}[{self.chat.id}]'")
        self.bot.CONVERSATION[self.chat.id] = asyncio.Queue(self._max_incoming)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        self.log.info(f"Closing conversation with '{self.chat.name}[{self.chat.id}]'")
        conv = self.bot.CONVERSATION[self.chat.id]

        conv.put_nowait(None)
        del self.bot.CONVERSATION[self.chat.id]
